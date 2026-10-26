import json
import threading
from pathlib import Path
from typing import Any

import pytest
from tests.support.checks import CLAIM_TEXT, PMID, SOURCE_ID, live_check
from tests.support.settings import make_settings

from bio_claim_check.app import recorded
from bio_claim_check.app.container import fake_check_claims, read_ledger, read_published_files
from bio_claim_check.app.recorded import RecordBusyError, record_check, record_question
from bio_claim_check.app.run_record import CheckInputs, RunInputs
from bio_claim_check.app.usecases.check_claim import live_claim
from bio_claim_check.app.usecases.published_run import load_published
from bio_claim_check.app.usecases.run import RunInputError, RunPorts
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.report.models import ClaimCheck, Report


def _rows(var_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in read_ledger(var_dir).splitlines()]


def test_a_fictional_question_is_published_and_loads(tmp_path: Path) -> None:
    result = record_question("Does OS-912 help?", AnswerMode.OVER_EAGER, 3, settings=None, var_dir=tmp_path)
    assert result.path == tmp_path / "runs" / result.run_id / "report.json"
    run = load_published(result.run_id, *read_published_files(tmp_path, result.run_id))
    assert run.artifact == result.artifact
    assert isinstance(run.artifact, Report)
    assert run.report == result.artifact
    assert run.manifest.command == "run"
    assert isinstance(run.manifest.inputs, RunInputs)
    assert [r["command"] for r in _rows(tmp_path)] == ["run"]


def test_a_fictional_check_is_published_and_loads(tmp_path: Path) -> None:
    claim = next(c for c in fake_check_claims() if c.id == "o1")
    result = record_check(claim, settings=None, var_dir=tmp_path)
    run = load_published(result.run_id, *read_published_files(tmp_path, result.run_id))
    assert isinstance(run.artifact, ClaimCheck)
    assert run.artifact == result.artifact
    assert run.report is None
    assert run.manifest.command == "check"
    assert run.manifest.provenance == "fake"
    assert isinstance(run.manifest.inputs, CheckInputs)
    assert run.manifest.inputs.source_id == "FAKE:1"
    assert run.manifest.llm == ()
    assert run.manifest.declared_llm == ()


def test_a_live_check_declares_only_the_verifier(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(recorded, "build_live_check_ports", live_check)
    seen: list[int] = []
    settings = make_settings(var_dir=tmp_path)
    result = record_check(
        live_claim(CLAIM_TEXT, PMID),
        settings=settings,
        var_dir=tmp_path,
        on_events=lambda e: seen.append(len(e)),
    )
    run = load_published(result.run_id, *read_published_files(tmp_path, result.run_id))
    assert run.manifest.provenance == "live"
    assert [d.agent for d in run.manifest.declared_llm] == ["verifier"]
    assert isinstance(run.manifest.inputs, CheckInputs)
    assert run.manifest.inputs.source_id == SOURCE_ID
    assert seen
    assert seen[0] > 0


def test_a_failed_run_still_reports_its_events_and_publishes_nothing(tmp_path: Path) -> None:
    seen: list[int] = []
    with pytest.raises(RunInputError):
        record_question(
            " ", AnswerMode.STRICT, 3, settings=None, var_dir=tmp_path, on_events=lambda e: seen.append(1)
        )
    assert seen == [1]
    assert not (tmp_path / "runs").exists() or not any((tmp_path / "runs").iterdir())
    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["run_id"] is None
    record_question("Does OS-912 help?", AnswerMode.STRICT, 3, settings=None, var_dir=tmp_path)  # lock freed


def test_a_second_run_while_one_is_recording_is_busy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    inside, release = threading.Event(), threading.Event()
    build = recorded.build_fake_run_ports

    def held(emitter: EventEmitter | None = None) -> RunPorts:
        inside.set()
        release.wait(timeout=10)
        return build(emitter)

    monkeypatch.setattr(recorded, "build_fake_run_ports", held)
    first = threading.Thread(
        target=record_question,
        args=("First?", AnswerMode.STRICT, 3),
        kwargs={"settings": None, "var_dir": tmp_path},
    )
    first.start()
    assert inside.wait(timeout=10)
    try:
        with pytest.raises(RecordBusyError, match="another run is in progress"):
            record_check(fake_check_claims()[0], settings=None, var_dir=tmp_path)
    finally:
        release.set()
        first.join()
    assert [r["command"] for r in _rows(tmp_path)] == ["run"]


def test_concurrent_runs_are_serialised_and_every_row_parses(tmp_path: Path) -> None:
    outcomes: list[str] = []
    start = threading.Barrier(4)

    def one(i: int) -> None:
        start.wait()
        try:
            record_question(f"Question {i}?", AnswerMode.STRICT, 3, settings=None, var_dir=tmp_path)
            outcomes.append("published")
        except RecordBusyError:
            outcomes.append("busy")

    threads = [threading.Thread(target=one, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rows = _rows(tmp_path)
    assert outcomes.count("published") == len(rows) >= 1
    assert len({r["run_id"] for r in rows}) == len(rows)
    for row in rows:
        load_published(row["run_id"], *read_published_files(tmp_path, row["run_id"]))
