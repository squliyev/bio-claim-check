"""The audit use case and its CLI: sheet export by cache replay, decisions bound to the seal and, for the
test split, to the active prompt freeze (I74)."""

import contextlib
import csv
import io
from collections.abc import Generator
from pathlib import Path

import pytest
from tests.support.corpus import SPEC_FILE, QueryLiteratureSource, dataset_files, world
from tests.support.papers import paper
from tests.support.settings import make_settings
from typer.testing import CliRunner

from bio_claim_check.app import cli
from bio_claim_check.app.container import (
    FreezeError,
    OutputConflictError,
    build_replay,
    load_corpus_spec,
    publish_audit,
    publish_sheet,
)
from bio_claim_check.app.settings import Settings
from bio_claim_check.app.usecases.build_corpus import pool_query
from bio_claim_check.app.usecases.corpus_audit import (
    AuditInputError,
    apply_decisions,
    export_sheet,
)
from bio_claim_check.engine.cache.policy import CacheMissError
from bio_claim_check.features.contracts.corpus import AuditRecord, CorpusSpec, CorpusSplit, SourceEntry
from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.corpus.audit_sheet import AuditSheetError
from bio_claim_check.features.corpus.layout import MANIFEST, SEALED, audit_file, sources_file
from bio_claim_check.features.corpus.seal import dataset_problems, sealed_bytes
from bio_claim_check.features.corpus.serialise import sha256_hex
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource

pytestmark = pytest.mark.unit
runner = CliRunner()
KIND = OverstatedReason.CERTAINTY_INFLATION  # the fixture world's only dev candidate kind (MED:11)
PROMPTS = "b" * 64
DEV, TEST = CorpusSplit.DEV, CorpusSplit.TEST
TEST_KIND = OverstatedReason.PRECLINICAL_TO_CLINICAL  # one test candidate in the fixture world
FREEZE = "f" * 64


def _spec() -> CorpusSpec:
    return load_corpus_spec(SPEC_FILE)


def _sealed() -> dict[str, bytes]:
    files = dataset_files()
    return {**files, SEALED: sealed_bytes(files[MANIFEST])}


def _filled(sheet: str, decision: str = "confirm", reason: str = "") -> str:
    rows = list(csv.DictReader(io.StringIO(sheet)))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({**row, "decision": decision, "reason": reason})
    return out.getvalue()


def _write(folder: Path, files: dict[str, bytes]) -> Path:
    for name, data in files.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return folder


# --- use case -------------------------------------------------------------------------------------


def test_export_lists_the_first_n_dev_candidates_with_their_abstracts() -> None:
    sheet = export_sheet(_sealed(), _spec(), KIND, QueryLiteratureSource(world()))
    rows = list(csv.DictReader(io.StringIO(sheet)))
    assert [r["source_id"] for r in rows] == ["MED:11"]
    assert rows[0]["abstract"].startswith("Mice received the drug.")
    assert (rows[0]["decision"], rows[0]["reason"]) == ("", "")


def test_export_refuses_an_unsealed_dataset() -> None:
    with pytest.raises(AuditInputError) as err:
        export_sheet(dataset_files(), _spec(), KIND, QueryLiteratureSource(world()))
    assert err.value.problems == ("the dataset is not intact and sealed:", f"{SEALED} is missing")


def test_export_refuses_a_kind_the_corpus_does_not_score() -> None:
    with pytest.raises(AuditInputError, match="background_as_result is not a trap kind"):
        export_sheet(
            _sealed(), _spec(), OverstatedReason.BACKGROUND_AS_RESULT, QueryLiteratureSource(world())
        )


def test_export_refuses_a_kind_without_dev_candidates() -> None:
    with pytest.raises(AuditInputError, match="no dev candidates of nonsignificant_as_effect"):
        export_sheet(
            _sealed(), _spec(), OverstatedReason.NONSIGNIFICANT_AS_EFFECT, QueryLiteratureSource(world())
        )


def test_export_refuses_an_abstract_that_drifted_from_the_dataset() -> None:
    pools = world()
    query = pool_query("OS-912 AND decline", _spec().cutoff)
    pools[query] = tuple(
        paper(11, abstract="A different text. It may help.") if p.source_id == "MED:11" else p
        for p in pools[query]
    )
    with pytest.raises(AuditInputError) as err:
        export_sheet(_sealed(), _spec(), KIND, QueryLiteratureSource(pools))
    assert err.value.problems == ("MED:11: the cached abstract does not match the dataset",)


def test_export_refuses_an_abstract_missing_from_the_replayed_pools() -> None:
    with pytest.raises(AuditInputError) as err:
        export_sheet(_sealed(), _spec(), KIND, QueryLiteratureSource({}))
    assert err.value.problems == ("MED:11: not found in its questions' cached pools",)


def test_export_stops_searching_once_every_abstract_is_found() -> None:
    source = QueryLiteratureSource(world())
    export_sheet(_sealed(), _spec(), KIND, source)
    assert source.calls == [(pool_query("OS-912 AND decline", _spec().cutoff), 100)]


def test_apply_builds_a_record_that_the_seal_check_accepts() -> None:
    files = _sealed()
    sheet = export_sheet(files, _spec(), KIND, QueryLiteratureSource(world()))
    summary = apply_decisions(files, _spec(), KIND, _filled(sheet), prompts_sha256=PROMPTS)
    record = AuditRecord.model_validate_json(summary.record)
    assert record.corpus_seal == sha256_hex(files[MANIFEST])
    assert record.prompts_sha256 == PROMPTS
    assert (summary.confirmed, summary.reviewed) == (1, 1)
    low, high = summary.interval
    assert (round(low, 4), high) == (0.2065, 1.0)
    assert dataset_problems({**files, audit_file(DEV, KIND): summary.record}, _spec()) == []


def test_apply_counts_rejections() -> None:
    files = _sealed()
    sheet = export_sheet(files, _spec(), KIND, QueryLiteratureSource(world()))
    summary = apply_decisions(
        files, _spec(), KIND, _filled(sheet, "reject", "hedge is the authors'"), prompts_sha256=PROMPTS
    )
    assert (summary.confirmed, summary.reviewed) == (0, 1)


def test_apply_refuses_a_sheet_that_skips_the_public_order() -> None:
    with pytest.raises(AuditSheetError):
        apply_decisions(_sealed(), _spec(), KIND, "source_id,decision,reason\n", prompts_sha256=PROMPTS)


@pytest.mark.parametrize("bad", ["", "B" * 64, "b" * 63, "g" * 64])
def test_apply_refuses_a_malformed_prompts_hash(bad: str) -> None:
    with pytest.raises(AuditInputError, match="64 lowercase hex"):
        apply_decisions(_sealed(), _spec(), KIND, "", prompts_sha256=bad)


def test_apply_refuses_an_unsealed_dataset() -> None:
    with pytest.raises(AuditInputError, match="not intact and sealed"):
        apply_decisions(dataset_files(), _spec(), KIND, "", prompts_sha256=PROMPTS)


def _test_sheet(files: dict[str, bytes]) -> str:
    return export_sheet(
        files, _spec(), TEST_KIND, QueryLiteratureSource(world()), split=TEST, freeze_sha256=FREEZE
    )


def test_a_test_sheet_lists_only_test_sources_under_a_header_with_the_seal_and_freeze() -> None:
    files = _sealed()
    header, body = _test_sheet(files).split("\n", 1)
    assert header == f"# test audit; corpus_seal={sha256_hex(files[MANIFEST])}; freeze_sha256={FREEZE}"
    lines = files[sources_file(TEST)].decode().splitlines()
    test_ids = {SourceEntry.model_validate_json(line).source_id for line in lines}
    rows = list(csv.DictReader(io.StringIO(body)))
    assert rows
    assert {r["source_id"] for r in rows} <= test_ids


def test_a_dev_sheet_lists_no_test_source() -> None:
    files = _sealed()
    sheet = export_sheet(files, _spec(), KIND, QueryLiteratureSource(world()))
    assert not sheet.startswith("#")
    assert [r["source_id"] for r in csv.DictReader(io.StringIO(sheet))] == ["MED:11"]  # a dev source


@pytest.mark.parametrize(("split", "freeze"), [(TEST, None), (DEV, FREEZE)])
def test_only_a_test_export_takes_the_freeze(split: CorpusSplit, freeze: str | None) -> None:
    with pytest.raises(AuditInputError, match="only a test audit uses it"):
        export_sheet(
            _sealed(), _spec(), KIND, QueryLiteratureSource(world()), split=split, freeze_sha256=freeze
        )


def test_a_test_record_carries_the_freeze_and_the_seal_check_accepts_it() -> None:
    files = _sealed()
    sheet = _test_sheet(files)
    header, body = sheet.split("\n", 1)
    summary = apply_decisions(
        files, _spec(), TEST_KIND, f"{header}\n{_filled(body)}", prompts_sha256=FREEZE, split=TEST
    )
    record = AuditRecord.model_validate_json(summary.record)
    assert (record.split, record.prompts_sha256) == (TEST, FREEZE)
    assert dataset_problems({**files, audit_file(TEST, TEST_KIND): summary.record}, _spec()) == []


@pytest.mark.parametrize(
    "header",
    [
        "",
        f"# test audit; corpus_seal={'0' * 64}; freeze_sha256={FREEZE}\n",
        "# test audit; corpus_seal={seal}; freeze_sha256=" + "e" * 64 + "\n",
    ],
)
def test_a_test_apply_refuses_a_sheet_without_this_seal_and_freeze(header: str) -> None:
    files = _sealed()
    body = _test_sheet(files).split("\n", 1)[1]
    sheet = header.format(seal=sha256_hex(files[MANIFEST])) + _filled(body)
    with pytest.raises(AuditInputError, match="not exported under this seal and the active prompt freeze"):
        apply_decisions(files, _spec(), TEST_KIND, sheet, prompts_sha256=FREEZE, split=TEST)


# --- container ------------------------------------------------------------------------------------


def test_publish_audit_is_once_only(tmp_path: Path) -> None:
    path = publish_audit(tmp_path, DEV, KIND, b"{}")
    assert path == tmp_path / audit_file(DEV, KIND)
    assert publish_audit(tmp_path, DEV, KIND, b"{}") == path
    with pytest.raises(OutputConflictError):
        publish_audit(tmp_path, DEV, KIND, b"{ }")
    assert path.read_bytes() == b"{}"


def test_publish_sheet_never_overwrites(tmp_path: Path) -> None:
    path = publish_sheet(tmp_path, DEV, KIND, "a\n")
    assert path.name == f"dev-{KIND.value}.csv"
    with pytest.raises(OutputConflictError):
        publish_sheet(tmp_path, DEV, KIND, "b\n")


def test_replay_never_fetches_even_when_settings_allow_it(tmp_path: Path) -> None:
    settings = make_settings(var_dir=tmp_path, cache_mode="read-write")
    with build_replay(settings) as source, pytest.raises(CacheMissError):
        source.search("anything", limit=1)


# --- CLI ------------------------------------------------------------------------------------------


@pytest.fixture
def replay(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BCC_CONTACT_EMAIL", "someone@example.org")
    monkeypatch.setenv("BCC_VAR_DIR", str(tmp_path / "var"))

    @contextlib.contextmanager
    def scripted(settings: Settings) -> Generator[BaseLiteratureSource]:
        del settings
        yield QueryLiteratureSource(world())

    monkeypatch.setattr(cli, "build_replay", scripted)


def _invoke(*argv: str) -> tuple[int, str, str]:
    result = runner.invoke(cli.app, ["corpus", *argv])
    return result.exit_code, result.stdout, result.stderr


@pytest.mark.usefixtures("replay")
def test_cli_sheet_then_apply_then_verify(tmp_path: Path) -> None:
    folder = _write(tmp_path / "ds", _sealed())
    out_dir = tmp_path / "audit"
    code, out, err = _invoke(
        "audit-sheet",
        "--kind",
        KIND.value,
        "--dataset",
        str(folder),
        "--out",
        str(out_dir),
        "--env-file",
        str(tmp_path / "none.env"),
    )
    assert code == 0, err
    sheet = out_dir / f"dev-{KIND.value}.csv"
    assert out.startswith(f"wrote: {sheet}\n")
    sheet.write_text(_filled(sheet.read_text()), encoding="utf-8")
    code, out, err = _invoke(
        "apply-audit",
        "--kind",
        KIND.value,
        "--sheet",
        str(sheet),
        "--prompts-sha256",
        PROMPTS,
        "--dataset",
        str(folder),
    )
    assert code == 0, err
    assert f"wrote: {folder / audit_file(DEV, KIND)}\n" in out
    assert "precision 1/1 confirmed (95% Wilson 0.21-1.00); author-confirmed, single rater" in out
    assert _invoke("verify", "--dataset", str(folder))[0] == 0


@pytest.mark.usefixtures("replay")
def test_cli_sheet_refuses_an_unsealed_dataset(tmp_path: Path) -> None:
    folder = _write(tmp_path / "ds", dataset_files())
    code, _, err = _invoke(
        "audit-sheet",
        "--kind",
        KIND.value,
        "--dataset",
        str(folder),
        "--out",
        str(tmp_path / "a"),
        "--env-file",
        str(tmp_path / "none.env"),
    )
    assert code == cli.ExitCode.DATASET
    assert f"{SEALED} is missing" in err
    assert not (tmp_path / "a").exists()


def test_cli_sheet_maps_a_cache_miss_to_exit_3(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BCC_CONTACT_EMAIL", "someone@example.org")
    monkeypatch.setenv("BCC_VAR_DIR", str(tmp_path / "var"))
    folder = _write(tmp_path / "ds", _sealed())
    code, _, err = _invoke(
        "audit-sheet",
        "--kind",
        KIND.value,
        "--dataset",
        str(folder),
        "--out",
        str(tmp_path / "a"),
        "--env-file",
        str(tmp_path / "none.env"),
    )
    assert code == cli.ExitCode.CACHE_MISS
    assert "built from the cache only" in err


def test_cli_apply_maps_errors_to_exit_codes(tmp_path: Path) -> None:
    folder = _write(tmp_path / "ds", _sealed())
    bad = tmp_path / "bad.csv"
    bad.write_text("source_id,decision,reason\nMED:999,confirm,\n", encoding="utf-8")
    base = ("apply-audit", "--kind", KIND.value, "--dataset", str(folder), "--sheet")
    assert _invoke(*base, str(bad), "--prompts-sha256", PROMPTS)[0] == cli.ExitCode.INPUT
    assert _invoke(*base, str(tmp_path / "missing.csv"), "--prompts-sha256", PROMPTS)[0] == cli.ExitCode.INPUT
    assert _invoke(*base, str(bad), "--prompts-sha256", "nothex")[0] == cli.ExitCode.DATASET
    assert not (folder / "audit").exists()


def test_cli_apply_refuses_to_replace_a_different_record(tmp_path: Path) -> None:
    files = _sealed()
    sheet_text = export_sheet(files, _spec(), KIND, QueryLiteratureSource(world()))
    folder = _write(tmp_path / "ds", files)
    sheet = tmp_path / "s.csv"
    sheet.write_text(_filled(sheet_text), encoding="utf-8")
    args = ("apply-audit", "--kind", KIND.value, "--dataset", str(folder), "--sheet", str(sheet))
    assert _invoke(*args, "--prompts-sha256", PROMPTS)[0] == 0
    assert _invoke(*args, "--prompts-sha256", PROMPTS)[0] == 0  # same record: a no-op
    code, _, _ = _invoke(*args, "--prompts-sha256", "c" * 64)
    assert code == cli.ExitCode.OUTPUT


@pytest.mark.usefixtures("replay")
def test_cli_test_split_sheet_then_apply_under_the_recomputed_freeze(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def frozen(*_: object) -> str:
        return FREEZE

    monkeypatch.setattr(cli, "active_freeze_sha256", frozen)
    folder = _write(tmp_path / "ds", _sealed())
    env = ("--env-file", str(tmp_path / "none.env"))
    common = ("--kind", TEST_KIND.value, "--split", "test", "--dataset", str(folder), *env)
    code, _, err = _invoke("audit-sheet", *common, "--out", str(tmp_path / "audit"))
    assert code == 0, err
    sheet = tmp_path / "audit" / f"test-{TEST_KIND.value}.csv"
    header, body = sheet.read_text(encoding="utf-8").split("\n", 1)
    sheet.write_text(f"{header}\n{_filled(body)}", encoding="utf-8")
    code, _, err = _invoke("apply-audit", *common, "--sheet", str(sheet))
    assert code == 0, err
    record = AuditRecord.model_validate_json((folder / audit_file(TEST, TEST_KIND)).read_bytes())
    assert (record.split, record.prompts_sha256) == (TEST, FREEZE)
    assert _invoke("verify", "--dataset", str(folder))[0] == 0


@pytest.mark.parametrize(
    ("split", "flag", "message"),
    [
        ("test", ("--prompts-sha256", PROMPTS), "refused for test"),
        ("dev", (), "required for dev"),
    ],
)
def test_cli_apply_takes_a_typed_hash_for_dev_only(
    tmp_path: Path, split: str, flag: tuple[str, ...], message: str
) -> None:
    folder = _write(tmp_path / "ds", _sealed())
    args = ("apply-audit", "--kind", KIND.value, "--split", split, "--dataset", str(folder))
    code, _, err = _invoke(*args, "--sheet", str(tmp_path / "s.csv"), *flag)
    assert code == cli.ExitCode.INPUT
    assert message in err


@pytest.mark.parametrize("command", ["audit-sheet", "apply-audit"])
def test_cli_test_split_is_closed_when_the_freeze_does_not_hold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str
) -> None:
    monkeypatch.setenv("BCC_CONTACT_EMAIL", "someone@example.org")
    monkeypatch.setenv("BCC_VAR_DIR", str(tmp_path / "var"))

    def stale(*_: object) -> str:
        raise FreezeError(["features/verify/verify_prompts.py: changed since freeze v1"])

    monkeypatch.setattr(cli, "active_freeze_sha256", stale)
    folder = _write(tmp_path / "ds", _sealed())
    extra = (
        ("--sheet", str(tmp_path / "s.csv")) if command == "apply-audit" else ("--out", str(tmp_path / "a"))
    )
    code, _, err = _invoke(
        command, "--kind", TEST_KIND.value, "--split", "test", "--dataset", str(folder), *extra,
        "--env-file", str(tmp_path / "none.env"),
    )  # fmt: skip
    assert code == cli.ExitCode.INPUT
    assert "this code is not the active frozen judge" in err
    assert "verify_prompts.py: changed since freeze v1" in err
    assert not (tmp_path / "a").exists()
    assert not (folder / "audit").exists()
