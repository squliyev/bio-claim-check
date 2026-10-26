"""The UI's data: the run list from the ledger (R6) and the complete About tables (R9), verdict by code."""

import json
from pathlib import Path
from typing import Any

import pytest

from bio_claim_check.app.container import fake_check_claims, read_ledger
from bio_claim_check.app.freeze import ACTIVE_FREEZE
from bio_claim_check.app.recorded import record_check, record_question
from bio_claim_check.app.settings import CHECKPOINT_RESULT
from bio_claim_check.app.ui.protocol import (
    ADJUST_LABEL,
    NO_RULE_LABEL,
    AboutLoadError,
    LedgerError,
    RunEntry,
    about_view,
    list_runs,
    load_about,
)
from bio_claim_check.app.usecases.proof_checkpoint import checkpoint
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.traps.counts import TrapResult

ROOT = Path(__file__).resolve().parents[4]
RESULT = ROOT / CHECKPOINT_RESULT


def _ledger(tmp_path: Path) -> tuple[str, str, list[dict[str, Any]]]:
    first = record_question("Does OS-912 help?", AnswerMode.STRICT, 3, settings=None, var_dir=tmp_path).run_id
    second = record_check(fake_check_claims()[0], settings=None, var_dir=tmp_path).run_id
    rows = [json.loads(line) for line in read_ledger(tmp_path).splitlines()]
    return first, second, rows


def _bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(json.dumps(r).encode() + b"\n" for r in rows)


def test_no_ledger_means_no_runs(tmp_path: Path) -> None:
    assert list_runs(read_ledger(tmp_path)) == ()


def test_runs_are_listed_most_recently_completed_first(tmp_path: Path) -> None:
    first, second, rows = _ledger(tmp_path)
    runs = list_runs(_bytes(rows))
    assert [(r.run_id, r.command) for r in runs] == [(second, "check"), (first, "run")]
    assert runs[0].finished_at == rows[1]["finished_at"].replace("Z", "+00:00")
    assert runs[0].label == f"{runs[0].finished_at} · check · {second}"


def test_failed_rows_other_commands_and_repeats_are_left_out(tmp_path: Path) -> None:
    first, second, rows = _ledger(tmp_path)
    failed = {**rows[0], "status": "failed", "code": "run.input", "run_id": None}
    other = {**rows[0], "command": "retractions"}
    cancelled = {**rows[1], "status": "cancelled", "code": None}
    again = dict(rows[0])  # the same run id completed again (identical inputs give the same id)
    ledger = _bytes([rows[0], failed, rows[1], other, cancelled, again]) + b"\n  \n"
    assert list_runs(ledger) == (
        RunEntry(first, "run", again["finished_at"].replace("Z", "+00:00")),
        RunEntry(second, "check", rows[1]["finished_at"].replace("Z", "+00:00")),
    )


def test_a_line_that_is_not_a_ledger_row_is_refused_not_skipped(tmp_path: Path) -> None:
    _, _, rows = _ledger(tmp_path)
    with pytest.raises(LedgerError, match="line 2 is not a ledger row"):
        list_runs(_bytes(rows[:1]) + b'{"command": "run"}\n' + _bytes(rows[1:]))


def test_the_about_view_carries_every_row_and_pair_table_of_the_result() -> None:
    raw = RESULT.read_bytes()
    data = json.loads(raw)
    about = about_view(raw)
    rows = [
        {"kind": r.kind, "role": r.role, "generator": r.generator, "n": r.n, "passed": r.passed}
        | {"needs_review": r.needs_review, "flagged": r.flagged, "failed": r.failed, "exact": r.exact}
        for r in about.rows
    ]
    assert rows == data["counts"]["rows"]
    pairs = [
        {"kind": p.kind, "generator": p.generator, "n": p.n, "table": [list(t) for t in p.table]}
        for p in about.pairs
    ]
    assert pairs == [{k: v for k, v in p.items() if k != "discriminated"} for p in data["counts"]["pairs"]]
    assert about.dispositions == ("passed", "needs_review", "flagged", "failed")
    assert about.verifier == data["verifier"]
    assert about.writer_family_flag is data["writer_family_flag"]


def test_the_about_verdict_is_the_one_code_computes_and_is_framed_as_adjust() -> None:
    raw = RESULT.read_bytes()
    point = checkpoint(TrapResult.model_validate_json(raw), ACTIVE_FREEZE)
    about = about_view(raw)
    assert about.verdict == point.verdict.value == "ADJUST"
    assert about.framing == ADJUST_LABEL
    assert "did not meet its predeclared bar" in about.framing
    assert [(r.name, r.value) for r in about.rules] == [
        ("model traps flagged", point.model_traps_flagged),
        ("parents passed", point.parents_passed),
        ("parents flagged", point.parents_flagged),
        ("failed", point.failed),
    ]
    assert all(r.met for r in about.rules) == (about.verdict == "GO")
    assert [r.denominator for r in about.rules] == [15, 16, 16, 38]


def test_a_result_without_a_predeclared_rule_shows_counts_but_no_verdict() -> None:
    data = json.loads(RESULT.read_bytes())
    data["trap_set_sha256"] = "0" * 64
    about = about_view(json.dumps(data).encode())
    assert about.verdict is None
    assert about.rules == ()
    assert about.framing == NO_RULE_LABEL
    assert len(about.rows) == len(data["counts"]["rows"])


def test_a_missing_or_unreadable_result_is_a_coded_error(tmp_path: Path) -> None:
    with pytest.raises(AboutLoadError, match="cannot read"):
        load_about(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"{")
    with pytest.raises(AboutLoadError, match="not a trap result"):
        load_about(bad)
    assert load_about(RESULT).verdict == "ADJUST"
