"""`retractions RUN_ID`: the run is checked before any request; the record lands beside, never inside, it.

Runs are produced by the real CLI on a scripted provider; a variant manifest is re-hashed with
`run_id_of`, so each refusal is reached through the hash chain, not around it.
"""

import contextlib
import hashlib
import json
from collections.abc import Callable, Generator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, override

import pytest
from tests.support.live_run import (
    ANSWER,
    PAPERS,
    QUESTION,
    SUPPORTED,
    Provider,
    invoke,
    ledger,
    run_dir,
    runner,
    use,
)
from tests.support.llm import response
from tests.support.papers import paper

from bio_claim_check.app import cli
from bio_claim_check.app.container import RETRACTIONS_DIR
from bio_claim_check.app.run_record import run_id_of
from bio_claim_check.app.settings import Settings
from bio_claim_check.app.usecases.retractions import (
    RetractionCheck,
    RetractionInputError,
    RetractionRow,
    cited_ids,
    load_checked_run,
    retraction_check,
    validate_run_id,
)
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.report.models import Report
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.retrieval.errors import RetrievalError
from bio_claim_check.features.retrieval.in_memory_literature_source import InMemoryLiteratureSource
from bio_claim_check.features.retrieval.models import RetractionStatus

pytestmark = pytest.mark.unit

AT = datetime(2027, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BCC_CONTACT_EMAIL", "someone@example.org")
    monkeypatch.setenv("BCC_VAR_DIR", str(tmp_path / "var"))


@pytest.fixture
def live_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """A recorded live run citing MED:11 (retrieved), MED:99 (not retrieved) and MED:1 (retrieved)."""
    use(monkeypatch, Provider(response(ANSWER), response(SUPPORTED), response(SUPPORTED)))
    code, _, err = invoke(tmp_path, "run", QUESTION, "--k", "2")
    assert code == 0, err
    return str(ledger(tmp_path)[0]["run_id"])


def _files(tmp_path: Path, run_id: str) -> tuple[bytes, bytes]:
    folder = run_dir(tmp_path, {"run_id": run_id})
    return (folder / "manifest.json").read_bytes(), (folder / "report.json").read_bytes()


def _variant(manifest: bytes, change: Callable[[dict[str, Any]], None]) -> tuple[bytes, str]:
    data = json.loads(manifest)
    change(data)
    raw = json.dumps(data).encode()
    return raw, run_id_of(raw)


# --- the integrity chain, before any request ------------------------------------------------------


@pytest.mark.parametrize("run_id", ["", "ABCDEF0123456789", "0123456789abcde", "../../etc/passwd", "0" * 17])
def test_a_malformed_run_id_is_refused(run_id: str) -> None:
    with pytest.raises(RetractionInputError, match="16 lowercase hex"):
        validate_run_id(run_id)


def test_a_live_run_loads(tmp_path: Path, live_run: str) -> None:
    report = load_checked_run(*_files(tmp_path, live_run), live_run)
    assert report.provenance == "live"
    assert cited_ids(report) == ("MED:1", "MED:11", "MED:99")


def _set_command(data: dict[str, Any]) -> None:
    data["command"] = "answer dev"


def _set_question_id(data: dict[str, Any]) -> None:
    data["inputs"]["question_id"] = "fx-glp1-q1"


def _set_fake(data: dict[str, Any]) -> None:
    data.update(provenance="fake", declared_llm=[])


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (_set_command, "not a recorded `run` report"),
        (_set_question_id, "a --dev run is a tuning record"),
        (_set_fake, "a fake run cites no real papers"),
    ],
    ids=["command", "dev", "fake-manifest"],
)
def test_a_run_of_the_wrong_kind_is_refused(
    tmp_path: Path, live_run: str, change: Callable[[dict[str, Any]], None], match: str
) -> None:
    manifest, artifact = _files(tmp_path, live_run)
    variant, run_id = _variant(manifest, change)
    with pytest.raises(RetractionInputError, match=match):
        load_checked_run(variant, artifact, run_id)


def test_a_manifest_that_does_not_hash_to_the_id_is_refused(tmp_path: Path, live_run: str) -> None:
    manifest, artifact = _files(tmp_path, live_run)
    with pytest.raises(RetractionInputError, match="does not hash to the run id"):
        load_checked_run(manifest, artifact, "0" * 16)


@pytest.mark.parametrize("manifest", [b"not json", b"{}"])
def test_a_manifest_that_does_not_parse_is_refused(manifest: bytes) -> None:
    with pytest.raises(RetractionInputError, match="manifest does not parse"):
        load_checked_run(manifest, b"", run_id_of(manifest))


def test_an_altered_report_is_refused(tmp_path: Path, live_run: str) -> None:
    manifest, artifact = _files(tmp_path, live_run)
    with pytest.raises(RetractionInputError, match="does not match its manifest"):
        load_checked_run(manifest, artifact + b" ", live_run)


def test_an_artifact_that_is_not_a_report_is_refused(tmp_path: Path, live_run: str) -> None:
    manifest, _ = _files(tmp_path, live_run)
    variant, run_id = _variant(
        manifest, lambda d: d["artifact"].update(sha256=hashlib.sha256(b"{}").hexdigest())
    )
    with pytest.raises(RetractionInputError, match="is not a report"):
        load_checked_run(variant, b"{}", run_id)


def test_a_fake_run_is_refused(tmp_path: Path) -> None:
    var = tmp_path / "var"
    assert runner.invoke(cli.app, ["run", QUESTION, "--fake", "--var-dir", str(var)]).exit_code == 0
    (row,) = ledger(tmp_path)
    with pytest.raises(RetractionInputError, match="a fake run cites no real papers"):
        load_checked_run(*_files(tmp_path, str(row["run_id"])), str(row["run_id"]))


def test_a_live_manifest_over_a_fake_report_is_refused(tmp_path: Path, live_run: str) -> None:
    fake = tmp_path / "fake"
    assert runner.invoke(cli.app, ["run", QUESTION, "--fake", "--var-dir", str(fake / "var")]).exit_code == 0
    (row,) = ledger(fake)
    _, fake_report = _files(fake, str(row["run_id"]))
    manifest, _ = _files(tmp_path, live_run)
    variant, run_id = _variant(
        manifest, lambda d: d["artifact"].update(sha256=hashlib.sha256(fake_report).hexdigest())
    )
    with pytest.raises(RetractionInputError, match=r"report\.json says fake, its manifest live"):
        load_checked_run(variant, fake_report, run_id)


# --- the fold ------------------------------------------------------------------------------------


def test_each_cited_id_gets_its_snapshot_and_its_current_status(tmp_path: Path, live_run: str) -> None:
    report = load_checked_run(*_files(tmp_path, live_run), live_run)
    statuses = (
        RetractionStatus(source_id="MED:1", retracted=True),
        RetractionStatus(source_id="MED:11", retracted=False),
        RetractionStatus(source_id="MED:99", retracted=None),
    )
    check = retraction_check(report, statuses, live_run, AT)
    assert check == RetractionCheck(
        run_id=live_run,
        checked_at=AT,
        papers=(
            RetractionRow(source_id="MED:1", retracted_in_run=False, retracted_now=True),
            RetractionRow(source_id="MED:11", retracted_in_run=False, retracted_now=False),
            RetractionRow(source_id="MED:99", retracted_in_run=None, retracted_now=None),
        ),
    )


def test_statuses_must_answer_every_cited_id_in_order(tmp_path: Path, live_run: str) -> None:
    report: Report = load_checked_run(*_files(tmp_path, live_run), live_run)
    with pytest.raises(ValueError, match="every cited id"):
        retraction_check(report, (RetractionStatus(source_id="MED:1", retracted=False),), live_run, AT)


# --- the command ---------------------------------------------------------------------------------


def _source(monkeypatch: pytest.MonkeyPatch, source: BaseLiteratureSource) -> list[Settings]:
    built: list[Settings] = []

    @contextlib.contextmanager
    def build(settings: Settings) -> Generator[BaseLiteratureSource]:
        built.append(settings)
        yield source

    monkeypatch.setattr(cli, "build_retraction_source", build)
    return built


def _tree(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def test_the_command_writes_a_numbered_record_beside_the_run_and_marks_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, live_run: str
) -> None:
    now = (paper(1, retracted=True),)  # MED:11 has since gone from the database
    _source(monkeypatch, InMemoryLiteratureSource(now))
    runs_before = _tree(tmp_path / "var" / "runs")
    first = invoke(tmp_path, "retractions", live_run)
    second = invoke(tmp_path, "retractions", live_run)
    assert (first[0], second[0]) == (0, 0), first[2]
    out = first[1]
    assert f"3 cited paper(s) of run {live_run}, re-checked uncached\n" in out
    assert "  MED:1: in run not retracted; now retracted  CHANGED\n" in out
    assert "  MED:11: in run not retracted; now not found\n" in out  # unknown is not a change
    assert "  MED:99: in run not retrieved; now not found\n" in out
    assert _tree(tmp_path / "var" / "runs") == runs_before
    records = sorted((tmp_path / "var" / RETRACTIONS_DIR).iterdir())
    assert len(records) == 2
    assert all(r.name.startswith(f"{live_run}-") for r in records)
    lines = records[0].read_bytes().splitlines()
    assert len(lines) == 1
    assert RetractionCheck.model_validate_json(lines[0]).run_id == live_run
    assert len(ledger(tmp_path)) == 1  # no ledger row for a re-check


@pytest.mark.parametrize("run_id", ["nope", "0" * 16])
def test_a_bad_or_unknown_run_id_is_an_input_error_before_any_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run_id: str
) -> None:
    built = _source(monkeypatch, InMemoryLiteratureSource(PAPERS))
    code, _, err = invoke(tmp_path, "retractions", run_id)
    assert code == cli.ExitCode.INPUT
    assert run_id in err
    assert built == []


class _Down(InMemoryLiteratureSource):
    @override
    def retraction_status(self, source_ids: Sequence[SourceId]) -> tuple[RetractionStatus, ...]:
        raise RetrievalError("Europe PMC returned HTTP 503")


def test_a_database_failure_is_an_upstream_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, live_run: str
) -> None:
    _source(monkeypatch, _Down(PAPERS))
    code, _, err = invoke(tmp_path, "retractions", live_run)
    assert code == cli.ExitCode.UPSTREAM
    assert "HTTP 503" in err


def test_an_unwritable_record_folder_is_an_output_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, live_run: str
) -> None:
    _source(monkeypatch, InMemoryLiteratureSource(PAPERS))
    (tmp_path / "var" / RETRACTIONS_DIR).write_text("a file, not a folder")
    code, _, err = invoke(tmp_path, "retractions", live_run)
    assert code == cli.ExitCode.OUTPUT
    assert "cannot write a retraction check" in err
