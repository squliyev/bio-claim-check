"""`run` live and `run --dev`, and `retractions`: the real agents, cache and verifier on a scripted provider.

`build_live_run_ports` is replaced by one that wires the real `LlmAnswerer` and `LlmVerifier` through one
in-memory cache shared across commands, so a read-only replay can be compared byte for byte (I65). The
provider-facing wiring itself is tested in `test_build_llm_clients.py`.
"""

import hashlib
import json
from pathlib import Path

import pytest
from tests.support.corpus import QueryLiteratureSource, dataset_files, world
from tests.support.live_run import (
    ANSWER,
    GPT,
    QUESTION,
    SUPPORTED,
    TRUNCATED,
    Provider,
    invoke,
    ledger,
    manifest,
    run_dir,
    runner,
    use,
)
from tests.support.llm import response

from bio_claim_check.app import cli
from bio_claim_check.engine.llm.errors import LlmProviderError
from bio_claim_check.engine.llm.messages import FinishReason, LlmResponse
from bio_claim_check.features.corpus.layout import MANIFEST, SEALED
from bio_claim_check.features.corpus.seal import sealed_bytes
from bio_claim_check.features.report.models import LIVE_NOTICE
from bio_claim_check.features.verify.verify_llm_agent import VerifyLlmAgent

pytestmark = pytest.mark.unit

DEV_Q = "fx-glp1-q1"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BCC_CONTACT_EMAIL", "someone@example.org")
    monkeypatch.setenv("BCC_VAR_DIR", str(tmp_path / "var"))


def test_a_live_run_verifies_each_retrieved_pair_and_records_both_models(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    use(monkeypatch, Provider(response(ANSWER), response(SUPPORTED), TRUNCATED))
    code, out, err = invoke(tmp_path, "run", QUESTION, "--k", "2")
    assert code == 0, err
    assert out.startswith(LIVE_NOTICE + "\n")
    assert "models: answerer=gpt-6.1-sol (openai), verifier=claude-opus-4-8 (anthropic)\n" in out
    assert "warning" not in err
    (row,) = ledger(tmp_path)
    assert (row["status"], row["command"]) == ("succeeded", "run")
    record_manifest = manifest(tmp_path, row)
    assert record_manifest["provenance"] == "live"
    assert record_manifest["inputs"]["question_sha256"] == hashlib.sha256(QUESTION.encode()).hexdigest()
    assert [d["agent"] for d in record_manifest["declared_llm"]] == ["answer_strict", "verifier"]
    assert sorted({u["agent"] for u in record_manifest["llm"]}) == ["answer_strict", "verifier"]
    report = json.loads((run_dir(tmp_path, row) / "report.json").read_text())
    assert report["models"]["same_family"] is False
    pairs = [p for c in report["claims"] for p in c["pairs"]]
    assert [p["outcome"] for p in pairs] == ["verdict", "citation_not_retrieved", "failure"]
    assert pairs[0]["verdict"]["evidence_status"] == "located"
    assert pairs[2]["disposition"] == "failed"


def test_a_read_only_replay_reproduces_the_report_and_the_manifest_byte_for_byte(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = use(monkeypatch, Provider(response(ANSWER), response(SUPPORTED), response(SUPPORTED)))
    assert invoke(tmp_path, "run", QUESTION, "--k", "2")[0] == 0
    first = {p.name: p.read_bytes() for p in run_dir(tmp_path, ledger(tmp_path)[0]).iterdir()}
    monkeypatch.setenv("BCC_CACHE_MODE", "read-only")
    code, _, err = invoke(tmp_path, "run", QUESTION, "--k", "2")
    assert code == 0, err
    live, replay = ledger(tmp_path)
    assert live["run_id"] == replay["run_id"]
    assert {p.name: p.read_bytes() for p in run_dir(tmp_path, replay).iterdir()} == first
    assert len(provider.client.requests) == 3


def test_same_family_models_are_allowed_but_flagged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    use(monkeypatch, Provider(response('{"claims": []}'), verifier=GPT))
    code, out, err = invoke(tmp_path, "run", QUESTION, "--k", "2")
    assert code == 0, err
    assert "verifier=gpt-6.1-sol (openai)" in out
    assert "warning: answerer and verifier are both openai models (not independent)" in err


def test_a_provider_error_in_the_verifier_stops_the_run_with_no_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    error = LlmProviderError(deployment="claude-opus-4-8", status=500, provider_code=None)
    use(monkeypatch, Provider(response(ANSWER), error))
    code, _, err = invoke(tmp_path, "run", QUESTION, "--k", "2")
    assert code == cli.ExitCode.PROVIDER
    assert error.code in err
    (row,) = ledger(tmp_path)
    assert (row["status"], row["code"], row["run_id"]) == ("failed", error.code, None)
    assert not (tmp_path / "var" / "runs").exists()


@pytest.mark.parametrize(
    "replies",
    [
        (response(ANSWER), response("{}", finish=FinishReason.CONTENT_FILTER), TRUNCATED),
        (response('{"claims": []}'),),
    ],
    ids=["every_verifier_call_failed", "abstained"],
)
def test_the_manifest_declares_the_verifier_prompt_even_when_no_verifier_call_finished(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, replies: tuple[LlmResponse, ...]
) -> None:
    use(monkeypatch, Provider(*replies))
    code, _, err = invoke(tmp_path, "run", QUESTION, "--k", "2")
    assert code == 0, err
    (row,) = ledger(tmp_path)
    declared = {d["agent"]: d["prompt_sha256"] for d in manifest(tmp_path, row)["declared_llm"]}
    assert declared["verifier"] == VerifyLlmAgent.prompt.sha256


def _dataset(tmp_path: Path) -> Path:
    files = dataset_files()
    files[SEALED] = sealed_bytes(files[MANIFEST])
    folder = tmp_path / "ds"
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    return folder


def test_a_dev_run_answers_from_the_dev_pool_and_records_its_drops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = Provider(
        response('{"claims": [{"text": "It helped mice.", "cites": ["MED:11"]}]}'), response(SUPPORTED)
    )
    provider.source = QueryLiteratureSource(world())
    use(monkeypatch, provider)
    folder = _dataset(tmp_path)
    code, out, err = invoke(tmp_path, "run", DEV_Q, "--dev", "--dataset", str(folder), "--k", "8")
    assert code == 0, err
    assert provider.datasets == [folder]  # the closed set comes from the dataset the run was checked against
    assert f"{DEV_Q}: 2 dev paper(s); dropped: not_dev=3\n" in out
    (row,) = ledger(tmp_path)
    record_manifest = manifest(tmp_path, row)
    assert record_manifest["inputs"]["question_id"] == DEV_Q
    assert (
        record_manifest["dataset_manifest_sha256"]
        == hashlib.sha256((folder / MANIFEST).read_bytes()).hexdigest()
    )
    record = json.loads((run_dir(tmp_path, row) / "report.json").read_text())
    assert (record["question_id"], record["papers"], record["usable"]) == (DEV_Q, ["MED:5", "MED:11"], 2)
    assert record["report"]["provenance"] == "live"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--fake", "--dev"], "--fake and --dev cannot be combined"),
        (["--fake", "--dataset", "ds"], "--fake reads no dataset or settings"),
        (["--var-dir", "v"], "--var-dir is for --fake"),
        (["--dataset", "ds"], "--dataset is for --dev"),
    ],
)
def test_a_wrong_flag_combination_is_an_input_error(tmp_path: Path, argv: list[str], message: str) -> None:
    result = runner.invoke(cli.app, ["run", QUESTION, *argv])
    assert result.exit_code == cli.ExitCode.INPUT
    assert message in result.stderr
    assert not (tmp_path / "var").exists()
