"""[RING:app] The judge fingerprint and the prompt freeze record (ADR 0020).

Why: a claim's disposition depends on more than the prompt text: on how the prompts are rendered and
sent (the JSON rendering, the provider codecs, the retry and repair loop, the rule-pack parser), on quote
location, the near-match threshold, the negation rules, the disposition table, the rule pack, the
fuzzy-matching library and the models and their parameters. The fingerprint hashes the exact bytes of
the files that hold those (`JUDGE_FILES`), the `rapidfuzz` version and both model specs (price
excluded: it judges nothing), so any edit to them, even to a docstring, is a different judge. That is
deliberately brittle: a frozen protocol fails closed. A freeze record binds one fingerprint to the
committed challenge result; `FROZEN` pins each record's exact bytes, and `ACTIVE_FREEZE` names the
one the code must still match (I73). A new judge needs a new record, a new pin and an ADR; an old
record is never edited.
It replaces the typed `--prompts-sha256` flag for test-split audits (ADR 0011: the freeze computes it).
Must not: read files or the environment (the container passes bytes and versions in), or call an LLM.

No LLM is involved in this module.
"""

import hashlib
from collections.abc import Mapping
from typing import Final, Self

from pydantic import JsonValue, model_validator

from bio_claim_check.common.canonical_json import compact_sha256
from bio_claim_check.common.models import NonBlankStr, Sha256Hex, ValidatedModel
from bio_claim_check.features.contracts.corpus import AuditRecord, CorpusSplit

JUDGE_FILES: Final[tuple[str, ...]] = (
    "common/canonical_json.py",
    "common/negation.py",
    "common/text.py",
    "data/rulepacks/default.yaml",
    "engine/agent/base_llm_agent.py",
    "engine/llm/anthropic_messages_codec.py",
    "engine/llm/codec_support.py",
    "engine/llm/messages.py",
    "engine/llm/openai_responses_codec.py",
    "engine/pipeline/llm_runner.py",
    "engine/prompts/prompt_template.py",
    "features/answer/answer_models.py",
    "features/answer/answer_prompts.py",
    "features/answer/over_eager_answer_llm_agent.py",
    "features/answer/strict_answer_llm_agent.py",
    "features/contracts/labels.py",
    "features/contracts/rulepack.py",
    "features/contracts/verdict.py",
    "features/verify/llm_verifier.py",
    "features/verify/verify_llm_agent.py",
    "features/verify/verify_models.py",
    "features/verify/verify_prompts.py",
)
"""Package files (paths under `bio_claim_check/`) whose bytes are part of the judge."""

FROZEN: Final[Mapping[str, str]] = {
    "v1": "17705069d842806ebe64fd7160496f83bdc35e5784629cafb13e274a7168edc1",
}
"""sha256 of each committed freeze record's exact bytes, by name. Records are never edited."""

ACTIVE_FREEZE: Final[str] = "v1"
"""The freeze the code must match (I73)."""

FREEZE_DIR: Final = "freeze"


class JudgeInputs(ValidatedModel):
    """Everything the fingerprint covers, kept readable so a mismatch names what changed."""

    files: dict[str, Sha256Hex]
    rapidfuzz: NonBlankStr
    answerer: dict[str, JsonValue]
    verifier: dict[str, JsonValue]

    @model_validator(mode="after")
    def _all_files(self) -> Self:
        if tuple(sorted(self.files)) != JUDGE_FILES:
            raise ValueError("files: exactly the JUDGE_FILES")
        return self

    @property
    def sha256(self) -> str:
        return compact_sha256(self.model_dump(mode="json"))


def judge_inputs(
    files: Mapping[str, bytes],
    rapidfuzz: str,
    answerer: Mapping[str, JsonValue],
    verifier: Mapping[str, JsonValue],
) -> JudgeInputs:
    """Hash each judge file; `answerer`/`verifier` are the model specs as JSON, without the price."""
    return JudgeInputs(
        files={name: hashlib.sha256(files[name]).hexdigest() for name in JUDGE_FILES},
        rapidfuzz=rapidfuzz,
        answerer=dict(answerer),
        verifier=dict(verifier),
    )


class FreezeRecord(ValidatedModel):
    """One frozen judge and the challenge result that cleared it. Hashes are checked on construction."""

    name: NonBlankStr
    judge: JudgeInputs
    judge_sha256: Sha256Hex
    challenge_result_sha256: Sha256Hex
    freeze_sha256: Sha256Hex

    @model_validator(mode="after")
    def _hashes(self) -> Self:
        if self.judge_sha256 != self.judge.sha256:
            raise ValueError("judge_sha256 does not match judge")
        if self.freeze_sha256 != _freeze_sha256(self.name, self.judge_sha256, self.challenge_result_sha256):
            raise ValueError("freeze_sha256 does not match the record")
        return self


def _freeze_sha256(name: str, judge_sha256: str, challenge_result_sha256: str) -> str:
    return compact_sha256(
        {"name": name, "judge_sha256": judge_sha256, "challenge_result_sha256": challenge_result_sha256}
    )


def freeze_record(name: str, judge: JudgeInputs, challenge_result: bytes) -> FreezeRecord:
    result_sha = hashlib.sha256(challenge_result).hexdigest()
    return FreezeRecord(
        name=name,
        judge=judge,
        judge_sha256=judge.sha256,
        challenge_result_sha256=result_sha,
        freeze_sha256=_freeze_sha256(name, judge.sha256, result_sha),
    )


def freeze_problems(committed: bytes, current: FreezeRecord, pins: Mapping[str, str] = FROZEN) -> list[str]:
    """Why `committed` is not the active freeze of this code: one line per problem, empty if it is."""
    pin = pins.get(current.name)
    if pin is None:
        return [f"freeze {current.name!r} is not pinned"]
    if hashlib.sha256(committed).hexdigest() != pin:
        return [f"freeze {current.name!r}: the file does not match its pinned sha256"]
    record = FreezeRecord.model_validate_json(committed)
    if record.name != current.name:
        return [f"the file holds freeze {record.name!r}, not {current.name!r}"]
    problems = [
        f"{name}: changed since freeze {record.name}"
        for name in JUDGE_FILES
        if record.judge.files[name] != current.judge.files[name]
    ]
    for field in ("rapidfuzz", "answerer", "verifier"):
        if getattr(record.judge, field) != getattr(current.judge, field):
            problems.append(f"{field}: changed since freeze {record.name}")
    if record.challenge_result_sha256 != current.challenge_result_sha256:
        problems.append(f"the challenge result changed since freeze {record.name}")
    return problems


def unfrozen_audits(audits: Mapping[str, bytes], records: Mapping[str, bytes]) -> list[str]:
    """Each test-split audit whose `prompts_sha256` is not the `freeze_sha256` of a committed record (I74).

    The CLI computes that hash; this check is how CI sees a record written any other way.
    """
    frozen = {FreezeRecord.model_validate_json(raw).freeze_sha256 for raw in records.values()}
    return [
        f"{name}: a test audit not made under a committed freeze"
        for name, raw in sorted(audits.items())
        if (record := AuditRecord.model_validate_json(raw)).split is CorpusSplit.TEST
        and record.prompts_sha256 not in frozen
    ]
