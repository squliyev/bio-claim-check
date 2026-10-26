"""`check`: one claim against one named paper, fictional offline and "live" on a scripted verifier."""

import json
from pathlib import Path

import pytest
from tests.support.checks import CLAIM_TEXT, NO_ABSTRACT_PMID, PMID, SOURCE_ID, live_check
from typer.testing import CliRunner

from bio_claim_check.app import cli, recorded
from bio_claim_check.features.report.models import CHECK_FAKE_NOTICE, CHECK_LIVE_NOTICE

pytestmark = pytest.mark.unit

runner = CliRunner()


def _invoke(*argv: str) -> tuple[int, str, str]:
    result = runner.invoke(cli.app, list(argv))
    if result.exception and not isinstance(result.exception, SystemExit):
        raise result.exception
    return result.exit_code, result.stdout, result.stderr


def _rows(var_dir: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in (var_dir / "ledger.jsonl").read_text().splitlines()]


def test_a_fictional_check_prints_the_verdict_and_records_it(tmp_path: Path) -> None:
    code, out, err = _invoke("check", "--fake", "o1", "--var-dir", str(tmp_path))
    assert code == 0, err
    assert out.startswith(CHECK_FAKE_NOTICE + "\n")
    assert "paper: FAKE:1 " in out
    assert "disposition: flagged\n" in out
    assert "label: overstated (preclinical_to_clinical)\n" in out
    assert "evidence (located): In APP/PS1 mice" in out
    (row,) = _rows(tmp_path)
    assert (row["command"], row["status"]) == ("check", "succeeded")
    assert f"check: {tmp_path / 'runs' / str(row['run_id']) / 'check.json'}\n" in out


def test_a_fictional_verifier_failure_is_shown_as_a_failure(tmp_path: Path) -> None:
    code, out, _ = _invoke("check", "--fake", "o6", "--var-dir", str(tmp_path))
    assert code == 0
    assert "verifier failed: structured_output\n" in out
    assert "disposition: failed\n" in out


def test_the_fictional_examples_are_listed(tmp_path: Path) -> None:
    code, out, _ = _invoke("check", "--fake", "list", "--var-dir", str(tmp_path))
    assert code == 0
    assert [line.split()[0] for line in out.splitlines()] == ["s1", "s3", "o1", "o2", "o3", "o4", "o6"]
    assert not (tmp_path / "ledger.jsonl").exists()


def test_an_unknown_fictional_example_lists_the_known_ones(tmp_path: Path) -> None:
    code, out, err = _invoke("check", "--fake", "o5", "--var-dir", str(tmp_path))
    assert code == cli.ExitCode.INPUT
    assert out == ""
    assert "no fictional example 'o5'" in err
    assert "o1  FAKE:1  " in err


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["check", "--fake", "o1", "--pmid", PMID], "drop --pmid and --env-file"),
        (["check", CLAIM_TEXT, "--pmid", PMID, "--var-dir", "x"], "--var-dir is for --fake"),
        (["check", CLAIM_TEXT], "needs --pmid"),
        (["check", CLAIM_TEXT, "--pmid", "12345678 OR 1"], "not a PMID"),
        (["check", " ", "--pmid", PMID], "must not be blank"),
    ],
)
def test_bad_arguments_fail_before_any_settings_or_request(argv: list[str], message: str) -> None:
    code, _, err = _invoke(*argv)
    assert code == cli.ExitCode.INPUT
    assert message in err


@pytest.fixture
def live_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("BCC_CONTACT_EMAIL", "someone@example.org")
    monkeypatch.setenv("BCC_VAR_DIR", str(tmp_path / "var"))
    monkeypatch.setattr(recorded, "build_live_check_ports", live_check)
    return tmp_path / "var"


def test_a_live_check_names_its_verifier_and_prints_usage(live_var: Path, tmp_path: Path) -> None:
    code, out, err = _invoke(
        "check", CLAIM_TEXT, "--pmid", f"PMID: {PMID}", "--env-file", str(tmp_path / "none.env")
    )
    assert code == 0, err
    assert out.startswith(CHECK_LIVE_NOTICE + "\n")
    assert "model: verifier=verifier-test (anthropic)\n" in out
    assert f"paper: {SOURCE_ID} " in out
    assert "llm calls:" in err
    (row,) = _rows(live_var)
    assert row["command"] == "check"


@pytest.mark.parametrize(
    ("pmid", "message"),
    [("87654321", "MED:87654321: no record"), (NO_ABSTRACT_PMID, "not a citable paper (no_abstract)")],
)
def test_a_paper_that_cannot_be_checked_is_an_input_error(
    live_var: Path, tmp_path: Path, pmid: str, message: str
) -> None:
    code, out, err = _invoke("check", CLAIM_TEXT, "--pmid", pmid, "--env-file", str(tmp_path / "none.env"))
    assert code == cli.ExitCode.INPUT
    assert message in err
    assert out == ""
    (row,) = _rows(live_var)
    assert row["run_id"] is None
