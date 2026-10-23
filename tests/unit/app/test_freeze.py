"""The judge fingerprint and the freeze record (I73): every input counts, records are pinned by bytes."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue, ValidationError
from tests.support.paths import ROOT
from tests.support.settings import make_settings

from bio_claim_check.app import container
from bio_claim_check.app.container import FreezeError, JudgeReadError, active_freeze_sha256, current_judge
from bio_claim_check.app.freeze import (
    ACTIVE_FREEZE,
    FROZEN,
    JUDGE_FILES,
    FreezeRecord,
    JudgeInputs,
    freeze_problems,
    freeze_record,
    judge_inputs,
    unfrozen_audits,
)
from bio_claim_check.common.canonical_json import pretty_json_bytes
from bio_claim_check.features.contracts.corpus import AuditDecision, AuditRecord, CorpusSplit
from bio_claim_check.features.contracts.labels import OverstatedReason

pytestmark = pytest.mark.unit

FILES = {name: name.encode() for name in JUDGE_FILES}
SPEC: dict[str, JsonValue] = {"deployment": "m", "params": {"max_output_tokens": 100}}
RESULT = b'{"score": "fictional"}\n'


def _judge(
    files: dict[str, bytes] | None = None,
    rapidfuzz: str = "3.14.6",
    answerer: dict[str, JsonValue] = SPEC,
    verifier: dict[str, JsonValue] = SPEC,
) -> JudgeInputs:
    return judge_inputs({**FILES, **(files or {})}, rapidfuzz, answerer, verifier)


def test_judge_files_are_sorted_and_unique() -> None:
    assert list(JUDGE_FILES) == sorted(set(JUDGE_FILES))


@pytest.mark.parametrize(
    "change",
    [
        {"files": {"features/verify/verify_prompts.py": b"edited"}},
        {"files": {"data/rulepacks/default.yaml": b"edited"}},
        {"rapidfuzz": "3.14.7"},
        {"answerer": {**SPEC, "deployment": "other"}},
        {"verifier": {**SPEC, "params": {"max_output_tokens": 101}}},
    ],
    ids=["prompt", "rulepack", "rapidfuzz", "answerer", "verifier"],
)
def test_every_input_changes_the_fingerprint(change: dict[str, Any]) -> None:
    assert _judge(**change).sha256 != _judge().sha256


def test_judge_inputs_must_name_exactly_the_judge_files() -> None:
    doc = _judge().model_dump(mode="json")
    doc["files"].pop(JUDGE_FILES[0])
    with pytest.raises(ValidationError, match="JUDGE_FILES"):
        JudgeInputs.model_validate(doc)


def test_freeze_record_hashes_are_checked_on_read() -> None:
    record = freeze_record("v1", _judge(), RESULT)
    assert record.challenge_result_sha256 == hashlib.sha256(RESULT).hexdigest()
    doc = record.model_dump(mode="json")
    assert FreezeRecord.model_validate(doc) == record
    with pytest.raises(ValidationError, match="judge_sha256"):
        FreezeRecord.model_validate({**doc, "judge_sha256": "0" * 64})
    with pytest.raises(ValidationError, match="freeze_sha256"):
        FreezeRecord.model_validate({**doc, "name": "v2"})


def _committed(record: FreezeRecord) -> tuple[bytes, dict[str, str]]:
    data = pretty_json_bytes(record.model_dump(mode="json"))
    return data, {record.name: hashlib.sha256(data).hexdigest()}


def test_the_active_freeze_matches_itself() -> None:
    data, pins = _committed(freeze_record("v1", _judge(), RESULT))
    assert freeze_problems(data, freeze_record("v1", _judge(), RESULT), pins) == []


def test_freeze_problems_name_what_changed() -> None:
    data, pins = _committed(freeze_record("v1", _judge(), RESULT))
    changed = _judge(files={"common/negation.py": b"edited"}, rapidfuzz="9", verifier={"deployment": "x"})
    assert freeze_problems(data, freeze_record("v1", changed, b"other"), pins) == [
        "common/negation.py: changed since freeze v1",
        "rapidfuzz: changed since freeze v1",
        "verifier: changed since freeze v1",
        "the challenge result changed since freeze v1",
    ]


def test_an_unpinned_edited_or_renamed_record_is_refused() -> None:
    current = freeze_record("v1", _judge(), RESULT)
    data, pins = _committed(current)
    assert freeze_problems(data, current, {}) == ["freeze 'v1' is not pinned"]
    assert freeze_problems(data + b"\n", current, pins) == [
        "freeze 'v1': the file does not match its pinned sha256"
    ]
    other, _ = _committed(freeze_record("v0", _judge(), RESULT))
    pins = {"v1": hashlib.sha256(other).hexdigest()}
    assert freeze_problems(other, current, pins) == ["the file holds freeze 'v0', not 'v1'"]


def test_every_pin_names_an_existing_record_and_the_active_one_is_pinned() -> None:
    assert ACTIVE_FREEZE in FROZEN


def test_the_installed_judge_reads_every_listed_file() -> None:
    judge = current_judge(make_settings())
    assert tuple(judge.files) == JUDGE_FILES
    assert judge.verifier["deployment"] == make_settings().verifier_model
    assert "price" not in judge.verifier


def test_a_missing_judge_file_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container, "JUDGE_FILES", ("features/verify/missing.py",))
    with pytest.raises(JudgeReadError, match=r"missing\.py"):
        current_judge(make_settings())


RECORDED = ROOT / "challenge" / "dev-v1.result.json"


def test_the_active_freeze_is_recomputed_from_the_code_and_committed_files() -> None:
    committed = json.loads((ROOT / "freeze" / f"{ACTIVE_FREEZE}.json").read_bytes())
    assert active_freeze_sha256(make_settings(), ROOT / "freeze", RECORDED) == committed["freeze_sha256"]


def test_the_active_freeze_refuses_a_missing_record(tmp_path: Path) -> None:
    with pytest.raises(FreezeError, match="cannot read the active freeze"):
        active_freeze_sha256(make_settings(), tmp_path, RECORDED)


def test_the_active_freeze_refuses_another_challenge_result(tmp_path: Path) -> None:
    other = tmp_path / "result.json"
    other.write_bytes(RECORDED.read_bytes() + b"\n")
    with pytest.raises(FreezeError, match="the challenge result changed since freeze v1"):
        active_freeze_sha256(make_settings(), ROOT / "freeze", other)


def test_the_active_freeze_refuses_a_missing_judge_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container, "JUDGE_FILES", ("features/verify/missing.py",))
    with pytest.raises(FreezeError, match=r"missing\.py"):
        active_freeze_sha256(make_settings(), ROOT / "freeze", RECORDED)


def _audit(split: CorpusSplit, prompts_sha256: str) -> bytes:
    decision = AuditDecision(source_id="PMID:1", decision="confirm", reason=None)
    record = AuditRecord(
        split=split,
        kind=next(iter(OverstatedReason)),
        corpus_seal="c" * 64,
        prompts_sha256=prompts_sha256,
        decisions=(decision,),
    )
    return pretty_json_bytes(record.model_dump(mode="json"))


def test_a_test_audit_must_carry_a_committed_freeze_hash() -> None:
    record = freeze_record("v1", _judge(), RESULT)
    records = {"v1.json": pretty_json_bytes(record.model_dump(mode="json"))}
    audits = {
        "frozen.json": _audit(CorpusSplit.TEST, record.freeze_sha256),
        "typed.json": _audit(CorpusSplit.TEST, "d" * 64),
        "dev.json": _audit(CorpusSplit.DEV, "d" * 64),
    }
    assert unfrozen_audits(audits, records) == ["typed.json: a test audit not made under a committed freeze"]
