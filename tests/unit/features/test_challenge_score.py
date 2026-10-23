"""The challenge pass rule (ADR 0020): unsafe passes, agreement with reasons, failures and absent evidence."""

import pytest
from pydantic import ValidationError

from bio_claim_check.features.bench.challenge import (
    MAX_CLAIM_WORDS,
    ChallengeItem,
    ChallengeOutcome,
    ChallengeScore,
    score,
)
from bio_claim_check.features.contracts.labels import (
    Disposition,
    EvidenceStatus,
    FailureKind,
    Label,
    NegationCheck,
    OverstatedReason,
)

pytestmark = pytest.mark.unit

_L, _E, _N, _D = Label, EvidenceStatus, NegationCheck, Disposition
CORR = OverstatedReason.CORRELATION_AS_CAUSATION


def item(n: int, expected: Label, reason: OverstatedReason | None = None) -> ChallengeItem:
    return ChallengeItem(
        id=f"ch{n:02d}",
        question_id="fx-glp1-q1",
        source_id=f"MED:{n}",
        abstract_sha256="a" * 64,
        claim="The drug lowered weight.",
        expected=expected,
        expected_reason=reason,
        label_source="ai_draft_author_confirmed",
    )


def judged(
    n: int,
    label: Label,
    status: EvidenceStatus,
    negation: NegationCheck,
    disposition: Disposition,
    reason: OverstatedReason | None = None,
) -> ChallengeOutcome:
    return ChallengeOutcome(
        id=f"ch{n:02d}",
        label=label,
        reason=reason,
        evidence_status=status,
        negation=negation,
        disposition=disposition,
        failure_kind=None,
    )


def failed(n: int) -> ChallengeOutcome:
    return ChallengeOutcome(
        id=f"ch{n:02d}",
        label=None,
        reason=None,
        evidence_status=None,
        negation=None,
        disposition=_D.FAILED,
        failure_kind=FailureKind.STRUCTURED_OUTPUT,
    )


def right(n: int, expected: Label) -> ChallengeOutcome:
    """The outcome a correct verifier gives for an item of `expected`."""
    return {
        _L.SUPPORTED: judged(n, _L.SUPPORTED, _E.LOCATED, _N.CLEAR, _D.PASSED),
        _L.OVERSTATED: judged(n, _L.OVERSTATED, _E.LOCATED, _N.CLEAR, _D.FLAGGED, CORR),
        _L.CONTRADICTED: judged(n, _L.CONTRADICTED, _E.LOCATED, _N.CLEAR, _D.FLAGGED),
        _L.NOT_IN_SOURCE: judged(n, _L.NOT_IN_SOURCE, _E.NOT_REQUIRED, _N.NOT_RUN, _D.FLAGGED),
    }[expected]


LABELS = [_L.SUPPORTED, _L.OVERSTATED, _L.CONTRADICTED, _L.NOT_IN_SOURCE] * 4
ITEMS = [item(n, label, CORR if label is _L.OVERSTATED else None) for n, label in enumerate(LABELS, 1)]
PERFECT = [right(n, label) for n, label in enumerate(LABELS, 1)]


def test_a_perfect_verifier_passes() -> None:
    s = score(ITEMS, PERFECT)
    assert (s.n, s.agree, s.unsafe_passes, s.failures_or_absent, s.passed) == (16, 16, 0, 0, True)
    assert s.table["supported"] == {"passed": 4}
    assert s.table["not_in_source"] == {"flagged": 4}


@pytest.mark.parametrize("expected_index", [2, 3])  # a contradicted and a not_in_source item
def test_one_unsafe_pass_fails_the_rule(expected_index: int) -> None:
    outcomes = list(PERFECT)
    outcomes[expected_index] = judged(expected_index + 1, _L.SUPPORTED, _E.LOCATED, _N.CLEAR, _D.PASSED)
    s = score(ITEMS, outcomes)
    assert (s.unsafe_passes, s.agree, s.passed) == (1, 15, False)


def test_agreement_floor_is_three_quarters() -> None:
    wrong = judged(1, _L.SUPPORTED, _E.LOCATED, _N.NEGATED, _D.NEEDS_REVIEW)
    outcomes = list(PERFECT)
    for i in (1, 5, 9, 13):  # four overstated items judged supported (negated, so not passed)
        outcomes[i] = wrong.model_validate({**wrong.model_dump(), "id": f"ch{i + 1:02d}"})
    s = score(ITEMS, outcomes)
    assert (s.agree, s.unsafe_passes, s.negated_supported, s.passed) == (12, 0, 4, True)
    outcomes[0] = judged(1, _L.CONTRADICTED, _E.LOCATED, _N.CLEAR, _D.FLAGGED)
    assert score(ITEMS, outcomes).passed is False


def test_an_overstated_item_needs_the_right_reason() -> None:
    outcomes = list(PERFECT)
    outcomes[1] = judged(2, _L.OVERSTATED, _E.LOCATED, _N.CLEAR, _D.FLAGGED, OverstatedReason.OTHER)
    assert score(ITEMS, outcomes).agree == 15


def test_failures_and_absent_evidence_are_capped_at_one_eighth() -> None:
    outcomes = list(PERFECT)
    outcomes[0] = failed(1)
    outcomes[4] = judged(5, _L.SUPPORTED, _E.ABSENT, _N.NOT_RUN, _D.FLAGGED)
    s = score(ITEMS, outcomes)
    assert (s.failures_or_absent, s.agree, s.passed) == (2, 15, True)
    outcomes[8] = judged(9, _L.SUPPORTED, _E.NEAR, _N.NOT_RUN, _D.NEEDS_REVIEW)
    outcomes[12] = failed(13)
    s = score(ITEMS, outcomes)
    assert (s.failures_or_absent, s.near, s.passed) == (3, 1, False)
    assert s.table["supported"] == {"failed": 2, "flagged": 1, "needs_review": 1}


@pytest.mark.parametrize(
    "outcomes",
    [[], PERFECT[:-1], [*PERFECT[:-1], PERFECT[0]], [*PERFECT, failed(99)]],
    ids=["empty", "missing", "duplicate", "extra"],
)
def test_items_and_outcomes_must_match_one_to_one(outcomes: list[ChallengeOutcome]) -> None:
    with pytest.raises(ValueError, match="same unique ids"):
        score(ITEMS, outcomes)


def test_duplicate_item_ids_are_refused() -> None:
    with pytest.raises(ValueError, match="same unique ids"):
        score([ITEMS[0], ITEMS[0]], [PERFECT[0]])


def test_claims_are_short_and_trimmed() -> None:
    base = ITEMS[0].model_dump()
    ChallengeItem.model_validate({**base, "claim": " ".join(["w"] * MAX_CLAIM_WORDS)})
    for claim in (" ".join(["w"] * (MAX_CLAIM_WORDS + 1)), " padded", "   "):
        with pytest.raises(ValidationError):
            ChallengeItem.model_validate({**base, "claim": claim})


def test_expected_reason_only_for_overstated() -> None:
    with pytest.raises(ValidationError, match="expected_reason"):
        item(1, _L.SUPPORTED, CORR)
    with pytest.raises(ValidationError, match="expected_reason"):
        item(1, _L.OVERSTATED)


def test_label_source_is_fixed() -> None:
    with pytest.raises(ValidationError):
        ChallengeItem.model_validate({**ITEMS[0].model_dump(), "label_source": "expert"})


@pytest.mark.parametrize(
    "fields",
    [
        {"failure_kind": "structured_output"},  # failed but judged
        {"disposition": "failed"},  # failed disposition without a failure kind
        {"evidence_status": None},  # judged without evidence status
    ],
)
def test_outcome_fields_are_consistent(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ChallengeOutcome.model_validate({**PERFECT[0].model_dump(), **fields})


def test_a_failed_outcome_carries_no_reason() -> None:
    with pytest.raises(ValidationError):
        ChallengeOutcome.model_validate({**failed(1).model_dump(), "reason": "other"})


def test_a_recorded_score_reads_back_only_if_passed_follows_from_the_counts() -> None:
    dumped = score(ITEMS, PERFECT).model_dump(mode="json")
    assert ChallengeScore.model_validate(dumped).passed is True
    with pytest.raises(ValidationError, match="does not follow"):
        ChallengeScore.model_validate({**dumped, "passed": False})
