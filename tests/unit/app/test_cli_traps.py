"""`traps generate | audit-sheet | apply-audit | verify`: exit codes and the files each step writes (S13).

The ports are replaced by scripted fakes over the fictional dev pool; the provider wiring is the same
`BaseLlmAgent` path every agent uses (tested in the LLM agent contract). `verify` runs under the real
active freeze, as the challenge and test-audit commands do.
"""

import contextlib
import csv
import io
import json
from collections.abc import Generator
from pathlib import Path

import pytest
from tests.support.corpus import SPEC_FILE, QueryLiteratureSource, dataset_files, world
from tests.support.live_run import CLAUDE, GPT, invoke, runner
from tests.support.paths import ROOT

from bio_claim_check.app import cli
from bio_claim_check.app.cli import ExitCode
from bio_claim_check.app.container import FreezeError, default_rulepack, load_corpus_spec
from bio_claim_check.app.settings import Settings
from bio_claim_check.app.usecases.challenge import ChallengePorts
from bio_claim_check.app.usecases.traps import TrapWriterPorts, draft_bytes, generate, parse_set
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.llm.model_spec import ModelSpec
from bio_claim_check.features.contracts.labels import Label, OverstatedReason
from bio_claim_check.features.contracts.verdict import VerifierOutput
from bio_claim_check.features.corpus.layout import MANIFEST, SEALED
from bio_claim_check.features.corpus.seal import sealed_bytes
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.traps.models import TrapDraft
from bio_claim_check.features.traps.scripted_trap_writer import ScriptedTrapWriter
from bio_claim_check.features.verify.scripted_verifier import ScriptedVerifier

pytestmark = pytest.mark.unit
DRAFT = TrapDraft(
    parent="Memory increased in treated mice.", trap="The drug is proven to restore memory in mice."
)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BCC_CONTACT_EMAIL", "someone@example.org")
    monkeypatch.setenv("BCC_VAR_DIR", str(tmp_path / "var"))


def _dataset(tmp_path: Path) -> Path:
    files = dataset_files()
    files[SEALED] = sealed_bytes(files[MANIFEST])
    folder = tmp_path / "ds"
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    return folder


def _writer(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []

    @contextlib.contextmanager
    def ports(
        settings: Settings, emitter: EventEmitter | None
    ) -> Generator[tuple[TrapWriterPorts, ModelSpec]]:
        del settings
        calls.append(1)
        writer = ScriptedTrapWriter({"MED:11": DRAFT})
        yield TrapWriterPorts(QueryLiteratureSource(world()), writer, default_rulepack(), emitter), GPT

    monkeypatch.setattr(cli, "build_trap_ports", ports)
    return calls


def _replay(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextlib.contextmanager
    def replay(settings: Settings) -> Generator[BaseLiteratureSource]:
        del settings
        yield QueryLiteratureSource(world())

    monkeypatch.setattr(cli, "build_replay", replay)


def _draft(tmp_path: Path) -> Path:
    """The draft `generate` would write for the fixture's one dev candidate (certainty inflation)."""
    ports = TrapWriterPorts(
        QueryLiteratureSource(world()), ScriptedTrapWriter({"MED:11": DRAFT}), default_rulepack()
    )
    files = dataset_files()
    files[SEALED] = sealed_bytes(files[MANIFEST])
    rows = generate(
        ports,
        files,
        load_corpus_spec(SPEC_FILE),
        per_kind=1,
        origin_id=GPT.deployment,
        max_live_calls=None,
        kinds=(OverstatedReason.CERTAINTY_INFLATION,),
    )
    path = tmp_path / "var" / "traps" / "dev-draft.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(draft_bytes(rows))
    return path


def test_generate_refuses_an_infeasible_target_before_any_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _writer(monkeypatch)
    code, _, err = invoke(
        tmp_path, "traps", "generate", "--per-kind", "1", "--dataset", str(_dataset(tmp_path))
    )
    assert (code, "cannot meet the target" in err) == (ExitCode.DATASET, True)
    assert not (tmp_path / "var" / "traps").exists()


def test_generate_refuses_a_budget_it_cannot_finish(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _writer(monkeypatch)
    monkeypatch.setenv("BCC_MAX_LIVE_LLM_CALLS", "1")
    code, _, err = invoke(
        tmp_path, "traps", "generate", "--per-kind", "1", "--dataset", str(ROOT / "datasets")
    )
    assert (code, "BCC_MAX_LIVE_LLM_CALLS is 1" in err) == (ExitCode.INPUT, True)


def _sheet(tmp_path: Path, draft: Path, folder: Path) -> Path:
    code, out, err = invoke(
        tmp_path,
        "traps",
        "audit-sheet",
        "--draft",
        str(draft),
        "--dataset",
        str(folder),
        "--out",
        str(tmp_path / "audit"),
    )
    assert code == 0, err
    (sheet,) = (tmp_path / "audit").iterdir()
    assert f"wrote: {sheet}" in out
    return sheet


def _apply(*argv: str) -> tuple[int, str, str]:
    """`traps apply-audit` reads no settings, so it takes no --env-file (like `corpus verify`)."""
    result = runner.invoke(cli.app, ["traps", "apply-audit", *argv])
    if result.exception and not isinstance(result.exception, SystemExit):
        raise result.exception
    return result.exit_code, result.stdout, result.stderr


def _confirm_all(sheet: Path) -> None:
    reader = csv.DictReader(io.StringIO(sheet.read_text(encoding="utf-8")))
    out = io.StringIO()
    writer: csv.DictWriter[str] = csv.DictWriter(out, fieldnames=reader.fieldnames or (), lineterminator="\n")
    writer.writeheader()
    writer.writerows({**row, "decision": "confirm"} for row in reader)
    sheet.write_text(out.getvalue(), encoding="utf-8")


def test_audit_sheet_then_apply_audit_writes_the_set_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _replay(monkeypatch)
    folder = _dataset(tmp_path)
    draft = _draft(tmp_path)
    sheet = _sheet(tmp_path, draft, folder)
    out = tmp_path / "traps" / "dev-v1.jsonl"
    args = ["--draft", str(draft), "--sheet", str(sheet), "--out", str(out), "--dataset", str(folder)]
    code, _, err = _apply(*args)
    assert (code, "should be 'confirm' or 'reject'" in err) == (ExitCode.INPUT, True)  # blank decisions
    assert not out.exists()
    _confirm_all(sheet)
    code, stdout, err = _apply(*args)
    assert code == 0, err
    assert "3 confirmed item(s)" in stdout
    assert len(parse_set(out.read_bytes())) == 3
    assert _apply(*args)[0] == 0  # same bytes: idempotent
    out.write_bytes(b"other\n")
    assert _apply(*args)[0] == ExitCode.OUTPUT


def test_an_edited_draft_is_refused_by_the_sheet(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _replay(monkeypatch)
    draft = _draft(tmp_path)
    draft.write_bytes(draft.read_bytes().replace(b'"claim":', b'"claim" :', 1))
    code, _, err = invoke(
        tmp_path, "traps", "audit-sheet", "--draft", str(draft), "--dataset", str(_dataset(tmp_path))
    )
    assert (code, "canonical" in err) == (ExitCode.INPUT, True)


def test_verify_writes_an_attempt_and_record_publishes_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _replay(monkeypatch)
    folder = _dataset(tmp_path)
    draft = _draft(tmp_path)
    sheet = _sheet(tmp_path, draft, folder)
    _confirm_all(sheet)
    traps = tmp_path / "traps" / "dev-v1.jsonl"
    apply = ["--draft", str(draft), "--sheet", str(sheet), "--out", str(traps), "--dataset", str(folder)]
    code, _, err = _apply(*apply)
    assert code == 0, err
    output = VerifierOutput(
        label=Label.SUPPORTED, overstated_reason=None, evidence="Memory improved.", reason="Ok."
    )
    script = {(i.id, i.source_id): output for i in parse_set(traps.read_bytes())}

    @contextlib.contextmanager
    def ports(
        settings: Settings, emitter: EventEmitter | None
    ) -> Generator[tuple[ChallengePorts, ModelSpec]]:
        del settings
        yield (
            ChallengePorts(
                QueryLiteratureSource(world()), ScriptedVerifier(script), default_rulepack(), emitter
            ),
            CLAUDE,
        )

    monkeypatch.setattr(cli, "build_challenge_ports", ports)

    def fresh(*_: object) -> str:
        return "f" * 64

    monkeypatch.setattr(cli, "active_freeze_sha256", fresh)
    args = ["--traps", str(traps), "--dataset", str(folder)]
    code, out, err = invoke(tmp_path, "traps", "verify", *args)
    assert code == 0, err
    assert "certainty_inflation trap model: n=1 flagged=0 passed=1" in out
    (attempt,) = (tmp_path / "var" / "traps" / "results").iterdir()
    code, out, err = invoke(tmp_path, "traps", "verify", *args, "--record")
    assert code == 0, err
    (recorded,) = (tmp_path / "traps" / "results").iterdir()
    assert recorded.name.endswith("-dev-v1.json")
    assert recorded.read_bytes() == attempt.read_bytes()
    assert json.loads(recorded.read_bytes())["writer_family_flag"] is False


def test_verify_refuses_a_stale_freeze_before_any_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def stale(*_: object) -> str:
        raise FreezeError(["features/verify/verify_prompts.py: changed since the freeze"])

    def no_ports(*_: object) -> None:
        raise AssertionError("no port may be built under a stale freeze")

    monkeypatch.setattr(cli, "active_freeze_sha256", stale)
    monkeypatch.setattr(cli, "build_challenge_ports", no_ports)
    traps = tmp_path / "dev-v1.jsonl"
    traps.write_bytes(b"{}\n")
    code, _, err = invoke(
        tmp_path, "traps", "verify", "--traps", str(traps), "--dataset", str(_dataset(tmp_path))
    )
    assert (code, "not the active frozen judge" in err, "changed since the freeze" in err) == (
        ExitCode.INPUT,
        True,
        True,
    )
