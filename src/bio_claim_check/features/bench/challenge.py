"""[RING:features/bench] The dev challenge set: items, verifier outcomes and the pass rule (ADR 0020).

Why: before the prompt freeze, the verifier must show on dev pairs that it does not let a contradicted
or unsupported claim pass, and that it mostly agrees with author-confirmed labels. The items are
curated (4 per label), AI-drafted and confirmed by the author (one rater, not an expert panel), so the
score is a regression floor, never an accuracy estimate. The rule below was committed before any model
saw the set; the CI attestation recomputes it from the committed outcomes.
Must not: read files, call a verifier, or hold abstract text (ADR 0008): an item names its source and
the abstract's hash, and its claim is a short author-written statement, not a sentence of the abstract.

No LLM is involved in this module.
"""

from collections import Counter
from collections.abc import Sequence
from typing import Annotated, Any, Literal, Self, cast

from pydantic import Field, ModelWrapValidatorHandler, computed_field, model_validator

from bio_claim_check.common.models import NonBlankStr, Sha256Hex, ValidatedModel
from bio_claim_check.features.contracts.ids import ClaimId, SourceId
from bio_claim_check.features.contracts.labels import (
    Disposition,
    EvidenceStatus,
    Label,
    NegationCheck,
    OverstatedReason,
)
from bio_claim_check.features.contracts.outcome import PairOutcome

MAX_CLAIM_WORDS = 30
"""A challenge claim is a short statement about an abstract, never a copied sentence of it (ADR 0020)."""

_UNSAFE: frozenset[Label] = frozenset({Label.CONTRADICTED, Label.NOT_IN_SOURCE})


class ChallengeItem(ValidatedModel):
    """One (claim, dev source) pair and the label the author confirmed for it."""

    id: ClaimId
    question_id: NonBlankStr
    source_id: SourceId
    abstract_sha256: Sha256Hex
    claim: NonBlankStr
    expected: Label
    expected_reason: OverstatedReason | None
    label_source: Literal["ai_draft_author_confirmed"]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        words = len(self.claim.split())
        if words > MAX_CLAIM_WORDS or self.claim != self.claim.strip():
            raise ValueError(f"claim: at most {MAX_CLAIM_WORDS} words, no surrounding whitespace")
        if (self.expected is Label.OVERSTATED) != (self.expected_reason is not None):
            raise ValueError("expected_reason: set if and only if expected is overstated")
        return self


ChallengeOutcome = PairOutcome
"""The challenge set's outcome record; the shared contract since S13."""


Count = Annotated[int, Field(strict=True, ge=0)]


class ChallengeScore(ValidatedModel):
    """The pre-registered pass rule (ADR 0020) and the counts it reads; `table` is reported, not gated."""

    n: Annotated[int, Field(strict=True, ge=1)]
    agree: Count
    unsafe_passes: Count
    failures_or_absent: Count
    negated_supported: Count
    near: Count
    table: dict[str, dict[str, Count]]

    @model_validator(mode="wrap")
    @classmethod
    def _recorded_passed(cls, data: Any, handler: ModelWrapValidatorHandler[Self]) -> Self:
        """A recorded score (its JSON dump) carries `passed`; it is read back only if the rule agrees."""
        recorded: object = None
        if isinstance(data, dict):
            data = dict(cast("dict[str, object]", data))
            recorded = data.pop("passed", None)
        built = handler(data)
        if recorded is not None and recorded != built.passed:
            raise ValueError("passed: does not follow from the counts")
        return built

    @computed_field
    @property
    def passed(self) -> bool:
        """No unsafe pass; agreement at least 3/4; failures plus absent evidence at most 1/8."""
        return (
            self.unsafe_passes == 0 and 4 * self.agree >= 3 * self.n and 8 * self.failures_or_absent <= self.n
        )


def _agrees(item: ChallengeItem, out: ChallengeOutcome) -> bool:
    return out.label is item.expected and out.reason is item.expected_reason


def score(items: Sequence[ChallengeItem], outcomes: Sequence[ChallengeOutcome]) -> ChallengeScore:
    """Score outcomes against items; both must hold exactly the same unique ids."""
    by_id = {o.id: o for o in outcomes}
    ids = [i.id for i in items]
    if not ids or len(set(ids)) != len(ids) or len(by_id) != len(outcomes) or set(ids) != by_id.keys():
        raise ValueError("items and outcomes must be non-empty and hold the same unique ids")
    pairs = [(item, by_id[item.id]) for item in items]
    table: dict[str, Counter[str]] = {label.value: Counter() for label in Label}
    for item, out in pairs:
        table[item.expected.value][out.disposition.value] += 1
    return ChallengeScore(
        n=len(pairs),
        agree=sum(_agrees(i, o) for i, o in pairs),
        unsafe_passes=sum(i.expected in _UNSAFE and o.disposition is Disposition.PASSED for i, o in pairs),
        failures_or_absent=sum(
            o.failure_kind is not None or o.evidence_status is EvidenceStatus.ABSENT for _, o in pairs
        ),
        negated_supported=sum(
            o.label is Label.SUPPORTED and o.negation is NegationCheck.NEGATED for _, o in pairs
        ),
        near=sum(o.evidence_status is EvidenceStatus.NEAR for _, o in pairs),
        table={label: dict(sorted(counts.items())) for label, counts in table.items()},
    )
