"""`Claim` and worst-case aggregation over every cited source (ADR 0006, I16)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from bio_claim_check.common.text import CleanedText, Span, clean_abstract
from bio_claim_check.features.contracts.labels import Disposition, FailureKind, Label, NegationCheck
from bio_claim_check.features.contracts.verdict import (
    Claim,
    Verdict,
    VerifierFailure,
    VerifierOutput,
    claim_disposition,
)

pytestmark = pytest.mark.unit

ABSTRACT = clean_abstract("Metformin reduced tumour growth in mice.")


def _clear(span: Span, text: CleanedText) -> NegationCheck:
    return NegationCheck.CLEAR


def _verdict(source: str, want: Disposition, claim: str = "c1") -> Verdict | VerifierFailure:
    if want is Disposition.FAILED:
        return VerifierFailure(claim_id=claim, source_id=source, kind=FailureKind.PROVIDER_ERROR)
    label = Label.CONTRADICTED if want is Disposition.FLAGGED else Label.SUPPORTED
    detector = _clear if want is Disposition.PASSED else None
    out = VerifierOutput(label=label, overstated_reason=None, evidence="reduced tumour growth", reason="r")
    verdict = Verdict.finalise(claim, source, out, ABSTRACT, detector)
    assert verdict.disposition is want
    return verdict


@pytest.mark.parametrize(
    ("dispositions", "expected"),
    [
        ((Disposition.PASSED,), Disposition.PASSED),
        ((Disposition.PASSED, Disposition.NEEDS_REVIEW), Disposition.NEEDS_REVIEW),
        ((Disposition.NEEDS_REVIEW, Disposition.FAILED), Disposition.FAILED),
        ((Disposition.FAILED, Disposition.FLAGGED, Disposition.PASSED), Disposition.FLAGGED),
    ],
)
def test_claim_disposition_worst_case(dispositions: tuple[Disposition, ...], expected: Disposition) -> None:
    sources = [f"MED:{i}" for i in range(len(dispositions))]
    claim = Claim(id="c1", text="t", cites=tuple(sources))
    outcomes = {s: _verdict(s, d) for s, d in zip(sources, dispositions, strict=True)}
    assert claim_disposition(claim, outcomes) is expected


@given(st.permutations(list(Disposition)))
def test_claim_disposition_ignores_order(order: list[Disposition]) -> None:
    sources = [f"MED:{d.value}" for d in order]
    claim = Claim(id="c1", text="t", cites=tuple(sources))
    outcomes = {s: _verdict(s, d) for s, d in zip(sources, order, strict=True)}
    assert claim_disposition(claim, outcomes) is Disposition.FLAGGED


def test_a_failure_is_always_failed() -> None:
    assert _verdict("MED:1", Disposition.FAILED).disposition is Disposition.FAILED


@pytest.mark.parametrize(
    ("outcomes", "message"),
    [
        pytest.param({"MED:1": Disposition.PASSED}, "no outcome", id="missing"),
        pytest.param(
            {"MED:1": Disposition.PASSED, "MED:2": Disposition.PASSED, "MED:3": Disposition.PASSED},
            "uncited",
            id="extra",
        ),
    ],
)
def test_claim_disposition_needs_exactly_the_cited_sources(
    outcomes: dict[str, Disposition], message: str
) -> None:
    claim = Claim(id="c1", text="t", cites=("MED:1", "MED:2"))
    with pytest.raises(ValueError, match=message):
        claim_disposition(claim, {s: _verdict(s, d) for s, d in outcomes.items()})


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param(_verdict("MED:1", Disposition.PASSED, claim="c2"), id="other-claim"),
        pytest.param(_verdict("MED:2", Disposition.PASSED), id="other-source"),
        pytest.param(_verdict("MED:2", Disposition.FAILED), id="failure-other-source"),
    ],
)
def test_claim_disposition_rejects_misfiled_outcomes(outcome: Verdict | VerifierFailure) -> None:
    claim = Claim(id="c1", text="t", cites=("MED:1",))
    with pytest.raises(ValueError, match="belongs to"):
        claim_disposition(claim, {"MED:1": outcome})


@pytest.mark.parametrize(
    ("data", "field"),
    [
        pytest.param({"cites": ()}, "cites", id="no-cites"),
        pytest.param({"cites": ("MED:1", "MED:1")}, "cites", id="duplicate-cites"),
        pytest.param({"text": "  "}, "text", id="blank-text"),
        pytest.param({"id": ""}, "id", id="empty-id"),
        pytest.param({"cites": ("pmid 1",)}, "cites", id="bad-source-id"),
    ],
)
def test_invalid_claims_are_rejected(data: dict[str, object], field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        Claim.model_validate({"id": "c1", "text": "t", "cites": ("MED:1",)} | data)


def test_claim_keeps_citation_order_and_is_frozen() -> None:
    claim = Claim.model_validate({"id": "c1", "text": "t", "cites": ["MED:2", "MED:1"]})
    assert claim.cites == ("MED:2", "MED:1")
    with pytest.raises(ValidationError, match="frozen"):
        claim.text = "u"


def test_cites_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="ordered list"):
        Claim.model_validate({"id": "c1", "text": "t", "cites": {"MED:1", "MED:2"}})


def test_claim_copies_cannot_skip_validation() -> None:
    claim = Claim(id="c1", text="t", cites=("MED:1", "MED:2"))
    with pytest.raises(TypeError, match="validated on construction"):
        claim.model_copy(update={"cites": ("MED:1", "MED:1")})
    assert claim.model_copy() == claim


@pytest.mark.parametrize("cites", [("MED:1", "MED:1"), ()])
def test_a_forged_claim_cannot_shrink_its_pairs(cites: tuple[str, ...]) -> None:
    forged = BaseModel.model_copy(Claim(id="c1", text="t", cites=("MED:1", "MED:2")), update={"cites": cites})
    assert isinstance(forged, Claim)
    with pytest.raises(ValueError, match="non-empty and unique"):
        claim_disposition(forged, {"MED:1": _verdict("MED:1", Disposition.PASSED)} if cites else {})


def test_failure_copies_cannot_skip_validation() -> None:
    failure = VerifierFailure(claim_id="c1", source_id="MED:1", kind=FailureKind.PROVIDER_ERROR)
    with pytest.raises(TypeError, match="validated on construction"):
        failure.model_copy(update={"claim_id": "not an id"})
