"""`challenge run [--record]` and `freeze write`: attempts kept by judge, one record, one freeze (I72, I73).

`build_challenge_ports` is replaced by a scripted verifier over the fictional dev pool; the provider
wiring itself is the same `LlmVerifier` path `run` uses (tested in `test_cli_run_live.py`).
"""

import contextlib
import hashlib
import json
from collections.abc import Generator
from pathlib import Path

import pytest
from tests.support.corpus import QueryLiteratureSource, dataset_files, world
from tests.support.live_run import CLAUDE, invoke
from tests.support.settings import make_settings

from bio_claim_check.app import cli
from bio_claim_check.app.cli import ExitCode
from bio_claim_check.app.container import build_challenge_ports, default_rulepack
from bio_claim_check.app.settings import Settings
from bio_claim_check.app.usecases.challenge import ChallengePorts
from bio_claim_check.engine.cache.policy import CacheMode
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.llm.model_spec import ModelSpec
from bio_claim_check.features.contracts.corpus import SourceEntry
from bio_claim_check.features.contracts.labels import FailureKind, Label
from bio_claim_check.features.contracts.verdict import VerifierOutput
from bio_claim_check.features.corpus.layout import DEV_SOURCES, MANIFEST, SEALED
from bio_claim_check.features.corpus.seal import sealed_bytes
from bio_claim_check.features.verify.llm_verifier import LlmVerifier
from bio_claim_check.features.verify.scripted_verifier import Script, ScriptedVerifier

pytestmark = pytest.mark.unit

SCRIPT: Script = {
    ("ch1", "MED:11"): VerifierOutput(
        label=Label.SUPPORTED, overstated_reason=None, evidence="Memory improved.", reason="Stated."
    ),
    ("ch2", "MED:5"): VerifierOutput(
        label=Label.NOT_IN_SOURCE, overstated_reason=None, evidence=None, reason="Not mentioned."
    ),
}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BCC_CONTACT_EMAIL", "someone@example.org")
    monkeypatch.setenv("BCC_VAR_DIR", str(tmp_path / "var"))


def _use(monkeypatch: pytest.MonkeyPatch, script: Script = SCRIPT) -> None:
    @contextlib.contextmanager
    def ports(
        settings: Settings, emitter: EventEmitter | None
    ) -> Generator[tuple[ChallengePorts, ModelSpec]]:
        del settings
        verifier = ScriptedVerifier(script)
        yield ChallengePorts(QueryLiteratureSource(world()), verifier, default_rulepack(), emitter), CLAUDE

    monkeypatch.setattr(cli, "build_challenge_ports", ports)


def _dataset(tmp_path: Path) -> Path:
    files = dataset_files()
    files[SEALED] = sealed_bytes(files[MANIFEST])
    folder = tmp_path / "ds"
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    return folder


def _challenge(tmp_path: Path, folder: Path, source_11: str = "MED:11") -> Path:
    shas = {
        e.source_id: e.abstract_sha256
        for e in map(SourceEntry.model_validate_json, (folder / DEV_SOURCES).read_text().splitlines())
    }
    rows = [
        ("ch1", source_11, "supported"),
        ("ch2", "MED:5", "not_in_source"),
    ]
    lines = [
        json.dumps(
            {
                "id": cid,
                "question_id": "fx-glp1-q1",
                "source_id": source,
                "abstract_sha256": shas.get(source, "c" * 64),
                "claim": "The drug improved memory in mice.",
                "expected": expected,
                "expected_reason": None,
                "label_source": "ai_draft_author_confirmed",
            }
        )
        for cid, source, expected in rows
    ]
    path = tmp_path / "challenge" / "dev-v1.jsonl"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def _args(tmp_path: Path, *extra: str) -> list[str]:
    folder = _dataset(tmp_path)
    return ["--challenge", str(_challenge(tmp_path, folder)), "--dataset", str(folder), *extra]


def test_run_keeps_the_attempt_and_record_publishes_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use(monkeypatch)
    args = _args(tmp_path)
    code, out, err = invoke(tmp_path, "challenge", "run", *args)
    assert code == 0, err
    assert "agree 2/2; unsafe passes 0" in out
    assert "challenge rule: met (author-confirmed, single rater; not accuracy)" in out
    (attempt,) = (tmp_path / "var" / "challenge").iterdir()
    assert not (tmp_path / "challenge" / "dev-v1.result.json").exists()
    code, out, err = invoke(tmp_path, "challenge", "run", *args, "--record")
    assert code == 0, err
    recorded = tmp_path / "challenge" / "dev-v1.result.json"
    assert recorded.read_bytes() == attempt.read_bytes()
    assert invoke(tmp_path, "challenge", "run", *args, "--record")[0] == 0  # same bytes: idempotent


def test_record_refuses_a_failing_rule(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _use(monkeypatch, {**SCRIPT, ("ch1", "MED:11"): FailureKind.PROVIDER_ERROR})
    code, out, err = invoke(tmp_path, "challenge", "run", *_args(tmp_path), "--record")
    assert code == ExitCode.INPUT
    assert "challenge rule: NOT met" in out
    assert "nothing recorded" in err
    assert not (tmp_path / "challenge" / "dev-v1.result.json").exists()


def test_bad_input_and_a_missing_source_have_their_exit_codes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use(monkeypatch)
    folder = _dataset(tmp_path)
    missing = tmp_path / "nope.jsonl"
    code, _, err = invoke(tmp_path, "challenge", "run", "--challenge", str(missing), "--dataset", str(folder))
    assert (code, "cannot read" in err) == (ExitCode.INPUT, True)
    bad = _challenge(tmp_path, folder, source_11="MED:1")  # a test source
    code, _, err = invoke(tmp_path, "challenge", "run", "--challenge", str(bad), "--dataset", str(folder))
    assert (code, "MED:1 is not a dev source" in err) == (ExitCode.INPUT, True)
    good = _challenge(tmp_path, folder)
    pools = {q: tuple(p for p in ps if p.source_id != "MED:11") for q, ps in world().items()}

    @contextlib.contextmanager
    def ports(
        settings: Settings, emitter: EventEmitter | None
    ) -> Generator[tuple[ChallengePorts, ModelSpec]]:
        del settings
        yield (
            ChallengePorts(QueryLiteratureSource(pools), ScriptedVerifier(SCRIPT), default_rulepack()),
            CLAUDE,
        )

    monkeypatch.setattr(cli, "build_challenge_ports", ports)
    code, _, err = invoke(tmp_path, "challenge", "run", "--challenge", str(good), "--dataset", str(folder))
    assert (code, "ch1" in err) == (ExitCode.DATASET, True)


def test_a_conflicting_attempt_is_not_overwritten(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _use(monkeypatch)
    args = _args(tmp_path)
    assert invoke(tmp_path, "challenge", "run", *args)[0] == 0
    (attempt,) = (tmp_path / "var" / "challenge").iterdir()
    attempt.write_bytes(b"other")
    code, _, err = invoke(tmp_path, "challenge", "run", *args)
    assert code == ExitCode.OUTPUT, err


def test_freeze_write_needs_an_attesting_record_and_writes_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use(monkeypatch)
    args = _args(tmp_path)
    out_dir = tmp_path / "freeze"
    code, _, err = invoke(tmp_path, "freeze", "write", *args, "--out", str(out_dir))
    assert (code, "dev-v1.result.json" in err) == (ExitCode.INPUT, True)  # nothing recorded yet
    assert invoke(tmp_path, "challenge", "run", *args, "--record")[0] == 0
    code, out, err = invoke(tmp_path, "freeze", "write", *args, "--out", str(out_dir))
    assert code == 0, err
    written = (out_dir / "v1.json").read_bytes()
    assert f"file sha256 (pin it in app/freeze.py FROZEN): {hashlib.sha256(written).hexdigest()}" in out
    record = json.loads(written)
    result = (tmp_path / "challenge" / "dev-v1.result.json").read_bytes()
    assert record["challenge_result_sha256"] == hashlib.sha256(result).hexdigest()
    assert invoke(tmp_path, "freeze", "write", *args, "--out", str(out_dir))[0] == 0  # same bytes


def test_freeze_write_refuses_a_result_from_another_judge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use(monkeypatch)
    args = _args(tmp_path)
    assert invoke(tmp_path, "challenge", "run", *args, "--record")[0] == 0
    monkeypatch.setenv("BCC_VERIFIER_MODEL", "gpt-6.1-sol")
    code, _, err = invoke(tmp_path, "freeze", "write", *args, "--out", str(tmp_path / "freeze"))
    assert code == ExitCode.INPUT
    assert "another judge" in err
    assert not (tmp_path / "freeze").exists()


def test_challenge_ports_in_read_only_mode_build_no_provider_client(tmp_path: Path) -> None:
    settings = make_settings(cache_mode=CacheMode.READ_ONLY, var_dir=tmp_path / "var")
    with build_challenge_ports(settings, None) as (ports, verifier):
        assert isinstance(ports.verifier, LlmVerifier)
        assert verifier.deployment == settings.verifier_model
