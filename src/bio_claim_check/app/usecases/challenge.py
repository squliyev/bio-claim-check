"""[RING:app/usecases] Run the dev challenge set through the verifier, and check items against the dataset.

Why: the verifier must clear the pre-registered challenge rule (ADR 0020) before the prompt freeze. Each
item's abstract comes from its dev question's sealed pool (`dev_papers`: the same preflight, search and
hash check as `run --dev`), so no test-split source can reach the verifier. Each item is judged exactly
as a live run judges a pair: the verifier port, then `Verdict.finalise` inside it. The result holds
labels, statuses and dispositions only, never quotes or reasons, so it can be committed (ADR 0008).
`item_problems` is also what the offline CI attestation runs on the committed dataset (I72).
Must not: do I/O itself, call a test question, retry or skip an item, or let a failed item disappear
(it is counted as `failed`).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from pydantic import ValidationError, model_validator

from bio_claim_check.app.usecases.answer_dev import dev_papers
from bio_claim_check.common.canonical_json import pretty_json_bytes
from bio_claim_check.common.errors import BccError
from bio_claim_check.common.models import NonBlankStr, Sha256Hex, ValidatedModel
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.features.bench.challenge import ChallengeItem, ChallengeOutcome, ChallengeScore, score
from bio_claim_check.features.contracts.corpus import CorpusSpec, CorpusSplit, QuestionEntry, SourceEntry
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.labels import Disposition
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.rulepack import RulePack
from bio_claim_check.features.contracts.verdict import Claim, Verdict
from bio_claim_check.features.corpus.layout import DEV_SOURCES, QUESTIONS
from bio_claim_check.features.corpus.seal import dataset_problems
from bio_claim_check.features.corpus.serialise import sha256_hex
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.verify.base_verifier import BaseVerifier


class ChallengeInputError(BccError):
    """The challenge file is malformed, or an item is not a sealed dev pair. One line per problem."""

    code = "challenge.input"

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = tuple(problems)


class ChallengePoolError(BccError):
    """An item's source did not come back, with its sealed hash, in its dev pool (an outage or drift)."""

    code = "challenge.pool"


@dataclass(frozen=True, slots=True)
class ChallengePorts:
    literature: BaseLiteratureSource
    verifier: BaseVerifier
    rules: RulePack
    emitter: EventEmitter | None = None


class ChallengeResult(ValidatedModel):
    """The committed record of one challenge run: which set, which judge, and what came out (I72)."""

    challenge_sha256: Sha256Hex
    judge_sha256: Sha256Hex
    verifier: NonBlankStr
    outcomes: tuple[ChallengeOutcome, ...]
    score: ChallengeScore

    @model_validator(mode="after")
    def _sorted(self) -> Self:
        ids = [o.id for o in self.outcomes]
        if ids != sorted(set(ids)):
            raise ValueError("outcomes: one per item, sorted by id")
        return self


def parse_items(data: bytes) -> tuple[ChallengeItem, ...]:
    """The challenge JSONL: one item per line, unique ids, at most one item per source."""
    problems: list[str] = []
    items: list[ChallengeItem] = []
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise ChallengeInputError(["the challenge file is not UTF-8"]) from None
    for number, line in enumerate(lines, start=1):
        try:
            items.append(ChallengeItem.model_validate_json(line))
        except ValidationError as err:
            problems.append(f"line {number}: {err.errors(include_input=False, include_url=False)[0]['msg']}")
    if not items and not problems:
        problems.append("the challenge file is empty")
    for field in ("id", "source_id"):
        values = [getattr(i, field) for i in items]
        if dupes := sorted({v for v in values if values.count(v) > 1}):
            problems.append(f"duplicate {field}: {', '.join(dupes)}")
    if problems:
        raise ChallengeInputError(problems)
    return tuple(items)


def item_problems(items: tuple[ChallengeItem, ...], files: Mapping[str, bytes]) -> list[str]:
    """Every item must name a dev question and a dev source in that question's pool, with its sealed hash."""
    questions = {
        q.id: q
        for q in (QuestionEntry.model_validate_json(x) for x in files[QUESTIONS].decode().splitlines())
    }
    sources = {
        e.source_id: e
        for e in (SourceEntry.model_validate_json(x) for x in files[DEV_SOURCES].decode().splitlines())
    }
    problems: list[str] = []
    for item in items:
        question = questions.get(item.question_id)
        entry = sources.get(item.source_id)
        if question is None or question.split is not CorpusSplit.DEV:
            problems.append(f"{item.id}: {item.question_id} is not a dev question")
        elif entry is None or entry.split is not CorpusSplit.DEV:
            problems.append(f"{item.id}: {item.source_id} is not a dev source")
        elif item.question_id not in {r.question_id for r in entry.ranks}:
            problems.append(f"{item.id}: {item.source_id} is not in the pool of {item.question_id}")
        elif item.abstract_sha256 != entry.abstract_sha256:
            problems.append(f"{item.id}: abstract_sha256 differs from the sealed dataset")
    return problems


def _outcome(item: ChallengeItem, ports: ChallengePorts, paper: Paper) -> ChallengeOutcome:
    claim = Claim(id=item.id, text=item.claim, cites=(item.source_id,))
    result = ports.verifier.verify(claim, paper, ports.rules)
    if not isinstance(result, Verdict):
        return ChallengeOutcome(
            id=item.id,
            label=None,
            reason=None,
            evidence_status=None,
            negation=None,
            disposition=Disposition.FAILED,
            failure_kind=result.kind,
        )
    return ChallengeOutcome(
        id=item.id,
        label=result.semantic_label,
        reason=result.overstated_reason,
        evidence_status=result.evidence_status,
        negation=result.negation,
        disposition=result.disposition,
        failure_kind=None,
    )


def run_challenge(
    ports: ChallengePorts,
    data: bytes,
    files: Mapping[str, bytes],
    spec: CorpusSpec,
    *,
    judge_sha256: str,
    verifier: str,
) -> ChallengeResult:
    """Check the set and the dataset (bad input raises before any fetch), then judge every item once."""
    items = parse_items(data)
    if problems := dataset_problems(files, spec):
        raise ChallengeInputError(["the dataset is not intact and sealed:", *problems])
    if problems := item_problems(items, files):
        raise ChallengeInputError(problems)
    pools: dict[str, dict[SourceId, Paper]] = {}
    for question_id in sorted({i.question_id for i in items}):
        _, pool = dev_papers(
            ports.literature, files, spec, question_id, k=spec.pool_hits, emitter=ports.emitter
        )
        pools[question_id] = {p.source_id: p for p in pool.papers}
    if missing := [i.id for i in items if i.source_id not in pools[i.question_id]]:
        raise ChallengePoolError(f"{', '.join(missing)}: the source did not come back in its dev pool")
    outcomes = tuple(
        _outcome(item, ports, pools[item.question_id][item.source_id])
        for item in sorted(items, key=lambda i: i.id)
    )
    return ChallengeResult(
        challenge_sha256=sha256_hex(data),
        judge_sha256=judge_sha256,
        verifier=verifier,
        outcomes=outcomes,
        score=score(items, outcomes),
    )


def result_bytes(result: ChallengeResult) -> bytes:
    """The canonical bytes of a result: what is written, committed and hashed by the freeze."""
    return pretty_json_bytes(result.model_dump(mode="json"))


def attestation_problems(
    data: bytes, result: bytes, files: Mapping[str, bytes], *, judge_sha256: str, verifier: str
) -> list[str]:
    """Why the committed result does not attest this challenge set and judge (I72); empty if it does.

    Self-reported: it proves the result is consistent with the set, the dataset and the code, not that a
    model produced it (ADR 0020).
    """
    try:
        items = parse_items(data)
        recorded = ChallengeResult.model_validate_json(result)
    except ChallengeInputError as err:
        return list(err.problems)
    except ValidationError as err:
        return [f"the result is not valid: {err.error_count()} problem(s)"]
    problems = item_problems(items, files)
    if result != result_bytes(recorded):
        problems.append("the result is not in canonical form")
    if recorded.challenge_sha256 != sha256_hex(data):
        problems.append("the result is for another challenge set")
    if recorded.judge_sha256 != judge_sha256:
        problems.append("the result was made by another judge (prompt, rules, code or model changed)")
    if recorded.verifier != verifier:
        problems.append(f"the result names verifier {recorded.verifier}, the code uses {verifier}")
    try:
        again = score(items, recorded.outcomes)
    except ValueError as err:
        return [*problems, str(err)]
    if again != recorded.score:
        problems.append("the recorded score does not match its outcomes")
    if not again.passed:
        problems.append("the challenge rule is not met")
    return problems
