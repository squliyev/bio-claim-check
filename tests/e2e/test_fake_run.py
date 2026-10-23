"""`bio-claim-check run --fake`, end to end (I18, I19, I20).

Golden files pin the whole report; hand-computed counts check it independently, so regenerating a
golden file (`--update-golden`) can never silently bless a wrong number.
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from tests.support.netblock import NETBLOCK_DIR
from tests.support.paths import ROOT, VENV_BIN
from typer.testing import CliRunner

from bio_claim_check.app.cli import app
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.report.models import FAKE_NOTICE

pytestmark = pytest.mark.e2e
runner = CliRunner()

Q = "Does OS-912 slow cognitive decline?"
GOLDEN = ROOT / "tests" / "fixtures" / "golden"

# Hand-computed from the scripts in features/answer/scripted_answerer.py and
# features/verify/scripted_verifier.py (see the S05 dev-log). Since S10 the negation check runs: the
# s1/FAKE:1 and s2/FAKE:3 sentences carry no cue (passed), the s3/FAKE:2 quote holds "did not" (review).
EXPECTED_COUNTS = {
    AnswerMode.STRICT: {
        "pair_counts": {"passed": 2, "needs_review": 1, "failed": 0, "flagged": 1},
        "claim_counts": {"passed": 1, "needs_review": 1, "failed": 0, "flagged": 1},
    },
    AnswerMode.OVER_EAGER: {
        "pair_counts": {"passed": 0, "needs_review": 1, "failed": 1, "flagged": 4},
        "claim_counts": {"passed": 0, "needs_review": 1, "failed": 1, "flagged": 4},
    },
}

EXPECTED_PASSED = {AnswerMode.STRICT: ["s1"], AnswerMode.OVER_EAGER: []}


def _run(var: Path, *args: str) -> tuple[str, Path]:
    result = runner.invoke(app, ["run", *args, "--var-dir", str(var)])
    assert result.exit_code == 0, result.output
    reports = list((var / "runs").glob("*/report.json"))
    assert len(reports) == 1
    return result.stdout, reports[0]


def _ledger(var: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in (var / "ledger.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("mode", list(AnswerMode))
def test_fake_run_matches_golden_and_hand_counts(
    mode: AnswerMode, tmp_path: Path, update_golden: bool
) -> None:
    stdout, path = _run(tmp_path, Q, "--fake", "--mode", mode.value)
    golden = GOLDEN / f"fake_run_{mode.value}.json"
    if update_golden:
        golden.write_bytes(path.read_bytes())
        pytest.fail(f"rewrote {golden.name}; review the diff and rerun without --update-golden")
    assert path.read_bytes() == golden.read_bytes()
    report = json.loads(path.read_bytes())
    assert {k: report[k] for k in ("pair_counts", "claim_counts")} == EXPECTED_COUNTS[mode]
    assert report["notice"] == FAKE_NOTICE
    assert stdout.splitlines()[0] == FAKE_NOTICE
    assert f"report: {path}" in stdout
    passed = [c["claim"]["id"] for c in report["claims"] if c["disposition"] == "passed"]
    assert passed == EXPECTED_PASSED[mode]


def test_a_second_run_is_byte_identical(tmp_path: Path) -> None:
    _, first = _run(tmp_path / "a", Q, "--fake")
    _, second = _run(tmp_path / "b", Q, "--fake")
    assert first.read_bytes() == second.read_bytes()
    manifest = (first.parent / "manifest.json").read_bytes()
    assert manifest == (second.parent / "manifest.json").read_bytes()
    assert first.parent.name == second.parent.name == hashlib.sha256(manifest).hexdigest()[:16]
    assert json.loads(manifest)["artifact"] == {
        "name": "report.json",
        "sha256": hashlib.sha256(first.read_bytes()).hexdigest(),
    }


def test_a_run_records_a_manifest_a_trace_and_one_ledger_row(tmp_path: Path) -> None:
    _, report = _run(tmp_path, Q, "--fake")
    manifest = json.loads((report.parent / "manifest.json").read_bytes())
    assert (manifest["command"], manifest["provenance"], manifest["llm"]) == ("run", "fake", [])
    assert manifest["inputs"] == {
        "question_id": None,
        "question_sha256": hashlib.sha256(Q.encode()).hexdigest(),
        "mode": "strict",
        "k": 4,
    }
    (row,) = _ledger(tmp_path)
    assert (row["status"], row["code"], row["run_id"], row["cache_mode"]) == (
        "succeeded",
        None,
        report.parent.name,
        None,
    )
    trace = (tmp_path / "events" / str(row["events"])).read_text().splitlines()
    stages = [(e["type"], e["stage"]) for e in map(json.loads, trace)]
    assert stages == [
        ("stage.started", "run"),
        *(p for s in ("retrieve", "answer", "verify") for p in (("stage.started", s), ("stage.finished", s))),
        ("stage.finished", "run"),
    ]


def test_non_ascii_question_is_echoed_exactly(tmp_path: Path) -> None:
    question = "Does OS-912 help cafe\u0301 workers — and β-cell function?"
    _, first = _run(tmp_path / "a", question, "--fake")
    _, second = _run(tmp_path / "b", question, "--fake")
    assert json.loads(first.read_text(encoding="utf-8"))["question"] == question
    assert first.parent.name == second.parent.name


def test_live_run_is_refused_until_s12(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", Q, "--var-dir", str(tmp_path)])
    assert result.exit_code == 2
    assert "use --fake" in result.output
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "args", [["   ", "--fake"], [Q, "--fake", "--k", "0"], [Q, "--fake", "--mode", "over-eager"]]
)
def test_bad_input_exits_2(args: list[str], tmp_path: Path) -> None:
    assert runner.invoke(app, ["run", *args, "--var-dir", str(tmp_path)]).exit_code == 2


def test_a_blank_question_is_recorded_as_a_failed_attempt(tmp_path: Path) -> None:
    assert runner.invoke(app, ["run", "   ", "--fake", "--var-dir", str(tmp_path)]).exit_code == 2
    (row,) = _ledger(tmp_path)
    assert (row["status"], row["code"], row["run_id"]) == ("failed", "run.input", None)
    assert not (tmp_path / "runs").exists()


def test_installed_script_ignores_hostile_env_and_writes_to_var_runs(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "BCC_CONTACT_EMAIL=not-an-email\nBCC_CACHE_MODE=bogus\nnot a dotenv line\n"
    )
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(NETBLOCK_DIR),  # I31: the subprocess blocks the network too
        "BCC_VAR_DIR": str(tmp_path / "elsewhere"),
        "BCC_CONTACT_EMAIL": "also-not-an-email",
        "BCC_FOUNDRY__API_KEY": "should-never-be-read",
    }
    result = subprocess.run(  # noqa: S603 -- fixed argv, our own console script from this venv
        [str(VENV_BIN / "bio-claim-check"), "run", Q, "--fake"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == FAKE_NOTICE
    reports = list((tmp_path / "var" / "runs").glob("*/report.json"))
    assert len(reports) == 1
    assert reports[0].read_bytes() == (GOLDEN / "fake_run_strict.json").read_bytes()
    assert (tmp_path / "var" / "ledger.jsonl").exists()
    assert not (tmp_path / "elsewhere").exists()
