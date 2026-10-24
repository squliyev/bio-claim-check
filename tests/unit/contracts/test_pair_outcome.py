"""`PairOutcome`: one item's verifier outcome, consistent by construction, built from a verdict or failure."""

import pytest
from pydantic import ValidationError

from bio_claim_check.common.text import clean_abstract
from bio_claim_check.features.contracts.labels import (
    Disposition,
    EvidenceStatus,
    FailureKind,
    Label,
    NegationCheck,
    OverstatedReason,
)
from bio_claim_check.features.contracts.outcome import PairOutcome
from bio_claim_check.features.contracts.verdict import Verdict, VerifierFailure, VerifierOutput

pytestmark = pytest.mark.unit

ABSTRACT = clean_abstract("In mice, compound Q reduced plaque load compared with vehicle.")
JUDGED: dict[str, object] = {
    "id": "t1",
    "label": Label.SUPPORTED,
    "reason": None,
    "evidence_status": EvidenceStatus.LOCATED,
    "negation": NegationCheck.CLEAR,
    "disposition": Disposition.PASSED,
    "failure_kind": None,
}
FAILED: dict[str, object] = {
    "id": "t1",
    "label": None,
    "reason": None,
    "evidence_status": None,
    "negation": None,
    "disposition": Disposition.FAILED,
    "failure_kind": FailureKind.PROVIDER_ERROR,
}


def test_valid_judged_and_failed_outcomes() -> None:
    assert PairOutcome.model_validate(JUDGED).disposition is Disposition.PASSED
    assert PairOutcome.model_validate(FAILED).failure_kind is FailureKind.PROVIDER_ERROR


@pytest.mark.parametrize(
    ("base", "change", "message"),
    [
        (FAILED, {"label": Label.SUPPORTED}, "a failed item has no label"),
        (FAILED, {"reason": OverstatedReason.OTHER}, "a failed item has no label"),
        (FAILED, {"disposition": Disposition.FLAGGED}, "failed if and only if"),
        (JUDGED, {"disposition": Disposition.FAILED}, "failed if and only if"),
        (JUDGED, {"negation": None}, "a judged item has"),
    ],
)
def test_inconsistent_outcomes_are_rejected(
    base: dict[str, object], change: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        PairOutcome.model_validate({**base, **change})


def test_of_a_verdict_keeps_labels_and_statuses_only() -> None:
    out = VerifierOutput(
        label=Label.OVERSTATED,
        overstated_reason=OverstatedReason.PRECLINICAL_TO_CLINICAL,
        evidence="compound Q reduced plaque load",
        reason="mice, not patients",
    )
    verdict = Verdict.finalise("opaque1", "MED:1", out, ABSTRACT)
    outcome = PairOutcome.of("item7", verdict)
    assert outcome == PairOutcome(
        id="item7",
        label=Label.OVERSTATED,
        reason=OverstatedReason.PRECLINICAL_TO_CLINICAL,
        evidence_status=EvidenceStatus.LOCATED,
        negation=NegationCheck.CLEAR,
        disposition=Disposition.FLAGGED,
        failure_kind=None,
    )


def test_of_a_failure_is_failed() -> None:
    failure = VerifierFailure(claim_id="opaque1", source_id="MED:1", kind=FailureKind.CONTENT_FILTERED)
    assert PairOutcome.of("item7", failure) == PairOutcome.model_validate(
        {**FAILED, "id": "item7", "failure_kind": FailureKind.CONTENT_FILTERED}
    )
