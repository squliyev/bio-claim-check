"""`Verdict` and the disposition table: total, impossible cells raise, evidence comes from code (I16)."""

import itertools

import pytest
from pydantic import ValidationError

from bio_claim_check.common.text import CleanedText, Span, clean_abstract, locate_quote
from bio_claim_check.features.contracts.labels import (
    Disposition,
    EvidenceStatus,
    Label,
    NegationCheck,
    OverstatedReason,
)
from bio_claim_check.features.contracts.verdict import (
    Verdict,
    VerifierOutput,
    disposition,
)

pytestmark = pytest.mark.unit

ABSTRACT = clean_abstract(
    "In this cohort, metformin treatment significantly reduced tumour growth in xenograft models "
    "compared with vehicle controls."
)
QUOTE = "metformin treatment significantly reduced tumour growth"


def _fields(label: Label, status: EvidenceStatus, negation: NegationCheck) -> dict[str, object]:
    """Every field other than the cell itself made consistent, so only the cell decides validity."""
    return {
        "claim_id": "c1",
        "source_id": "MED:1",
        "semantic_label": label,
        "overstated_reason": OverstatedReason.CERTAINTY_INFLATION if label is Label.OVERSTATED else None,
        "reason": "because",
        "evidence_quote": None if status is EvidenceStatus.NOT_REQUIRED else QUOTE,
        "evidence_status": status,
        "evidence_span": Span(0, 4) if status is EvidenceStatus.LOCATED else None,
        "negation": negation,
    }


def _table_or_none(label: Label, status: EvidenceStatus, negation: NegationCheck) -> Disposition | None:
    try:
        return disposition(label, status, negation)
    except ValueError:
        return None


CELLS = list(itertools.product(Label, EvidenceStatus, NegationCheck))


@pytest.mark.parametrize(("label", "status", "negation"), CELLS, ids=lambda c: c.value)
def test_every_cell_is_table_or_impossible(
    label: Label, status: EvidenceStatus, negation: NegationCheck
) -> None:
    expected = _table_or_none(label, status, negation)
    if expected is None:
        with pytest.raises(ValidationError, match="impossible verdict"):
            Verdict.model_validate(_fields(label, status, negation))
        return
    verdict = Verdict.model_validate(_fields(label, status, negation))
    assert verdict.disposition is expected
    restored = Verdict.model_validate_json(verdict.model_dump_json())
    assert restored == verdict
    assert hash(restored) == hash(verdict)


def test_table_matches_adr_0006() -> None:
    """The readable summary of the table, so a change to it is a visible, reviewed diff."""
    passed = {c for c in CELLS if _table_or_none(*c) is Disposition.PASSED}
    review = {c for c in CELLS if _table_or_none(*c) is Disposition.NEEDS_REVIEW}
    possible = {c for c in CELLS if _table_or_none(*c) is not None}
    assert passed == {(Label.SUPPORTED, EvidenceStatus.LOCATED, NegationCheck.CLEAR)}
    assert review == {
        (Label.SUPPORTED, EvidenceStatus.LOCATED, NegationCheck.NEGATED),
        (Label.SUPPORTED, EvidenceStatus.LOCATED, NegationCheck.NOT_RUN),
        (Label.SUPPORTED, EvidenceStatus.NEAR, NegationCheck.NOT_RUN),
    }
    assert len(possible) == 16
    assert all(_table_or_none(*c) is not Disposition.FAILED for c in CELLS)


@pytest.mark.parametrize(
    ("change", "field"),
    [
        pytest.param(
            {"overstated_reason": OverstatedReason.OTHER}, "overstated_reason", id="reason-on-supported"
        ),
        pytest.param({"evidence_quote": None}, "evidence_quote", id="located-without-quote"),
        pytest.param({"evidence_span": None}, "evidence_span", id="located-without-span"),
        pytest.param({"reason": " "}, "reason", id="blank-reason"),
        pytest.param({"evidence_quote": ""}, "evidence_quote", id="blank-quote"),
        pytest.param({"claim_id": "has space"}, "claim_id", id="bad-claim-id"),
        pytest.param({"source_id": "12345"}, "source_id", id="unnamespaced-source"),
        pytest.param({"extra": 1}, "extra", id="extra-field"),
    ],
)
def test_inconsistent_fields_are_rejected(change: dict[str, object], field: str) -> None:
    base = _fields(Label.SUPPORTED, EvidenceStatus.LOCATED, NegationCheck.CLEAR)
    with pytest.raises(ValidationError, match=field):
        Verdict.model_validate(base | change)


def test_span_on_a_non_located_verdict_is_rejected() -> None:
    base = _fields(Label.SUPPORTED, EvidenceStatus.NEAR, NegationCheck.NOT_RUN)
    with pytest.raises(ValidationError, match="evidence_span"):
        Verdict.model_validate(base | {"evidence_span": Span(0, 4)})


def test_quote_on_not_in_source_is_rejected() -> None:
    base = _fields(Label.NOT_IN_SOURCE, EvidenceStatus.NOT_REQUIRED, NegationCheck.NOT_RUN)
    with pytest.raises(ValidationError, match="evidence_quote"):
        Verdict.model_validate(base | {"evidence_quote": QUOTE})


@pytest.mark.parametrize("bad", [True, "1", 1.0])
def test_span_offsets_from_json_must_be_ints(bad: object) -> None:
    base = _fields(Label.SUPPORTED, EvidenceStatus.LOCATED, NegationCheck.CLEAR)
    with pytest.raises(ValidationError, match="JSON integers"):
        Verdict.model_validate(base | {"evidence_span": {"start": bad, "end": 5}})
    with pytest.raises(ValidationError, match="JSON integers"):
        Verdict.model_validate(base | {"evidence_span": {"start": 0, "end": bad}})


def _clear(span: Span, text: CleanedText) -> NegationCheck:
    assert span.of(text)
    return NegationCheck.CLEAR


def _negated(span: Span, text: CleanedText) -> NegationCheck:
    return NegationCheck.NEGATED


def _never(span: Span, text: CleanedText) -> NegationCheck:
    raise AssertionError("the detector must only run on a located span")


def _out(label: Label, evidence: str | None, reason: OverstatedReason | None = None) -> VerifierOutput:
    return VerifierOutput(label=label, overstated_reason=reason, evidence=evidence, reason="because")


def test_finalise_locates_the_quote_in_code() -> None:
    v = Verdict.finalise("c1", "MED:1", _out(Label.SUPPORTED, QUOTE), ABSTRACT, _clear)
    assert v.evidence_status is EvidenceStatus.LOCATED
    assert v.evidence_span == locate_quote(QUOTE, ABSTRACT)
    assert v.disposition is Disposition.PASSED


def test_finalise_without_a_negation_check_needs_review() -> None:
    v = Verdict.finalise("c1", "MED:1", _out(Label.SUPPORTED, QUOTE), ABSTRACT)
    assert v.negation is NegationCheck.NOT_RUN
    assert v.disposition is Disposition.NEEDS_REVIEW


@pytest.mark.parametrize(
    ("quote", "status", "expected"),
    [
        pytest.param(
            "metformin treatment significantly increased tumour growth",
            EvidenceStatus.NEAR,
            Disposition.NEEDS_REVIEW,
            id="near",
        ),
        pytest.param(
            "aspirin cured every patient", EvidenceStatus.ABSENT, Disposition.FLAGGED, id="fabricated"
        ),
    ],
)
def test_finalise_routes_unlocated_quotes(quote: str, status: EvidenceStatus, expected: Disposition) -> None:
    v = Verdict.finalise("c1", "MED:1", _out(Label.SUPPORTED, quote), ABSTRACT)
    assert (v.evidence_status, v.evidence_span, v.disposition) == (status, None, expected)


def test_finalise_keeps_the_llm_label_when_evidence_is_absent() -> None:
    v = Verdict.finalise("c1", "MED:1", _out(Label.CONTRADICTED, "not in the text at all"), ABSTRACT)
    assert v.semantic_label is Label.CONTRADICTED
    assert v.evidence_status is EvidenceStatus.ABSENT


def test_finalise_not_in_source_needs_no_evidence() -> None:
    v = Verdict.finalise("c1", "MED:1", _out(Label.NOT_IN_SOURCE, None), ABSTRACT)
    assert (v.evidence_status, v.evidence_quote, v.disposition) == (
        EvidenceStatus.NOT_REQUIRED,
        None,
        Disposition.FLAGGED,
    )


def test_finalise_carries_the_overstated_reason() -> None:
    out = _out(Label.OVERSTATED, QUOTE, OverstatedReason.PRECLINICAL_TO_CLINICAL)
    v = Verdict.finalise("c1", "MED:1", out, ABSTRACT)
    assert v.overstated_reason is OverstatedReason.PRECLINICAL_TO_CLINICAL
    assert v.disposition is Disposition.FLAGGED


@pytest.mark.parametrize("quote", ["nothing like it", None])
def test_finalise_runs_the_detector_only_on_a_located_span(quote: str | None) -> None:
    label = Label.NOT_IN_SOURCE if quote is None else Label.SUPPORTED
    v = Verdict.finalise("c1", "MED:1", _out(label, quote), ABSTRACT, _never)
    assert v.negation is NegationCheck.NOT_RUN


def test_finalise_records_a_negated_span_for_review() -> None:
    v = Verdict.finalise("c1", "MED:1", _out(Label.SUPPORTED, QUOTE), ABSTRACT, _negated)
    assert (v.negation, v.disposition) == (NegationCheck.NEGATED, Disposition.NEEDS_REVIEW)


def test_verify_against_accepts_its_own_abstract() -> None:
    for out in (
        _out(Label.SUPPORTED, QUOTE),
        _out(Label.NOT_IN_SOURCE, None),
        _out(Label.SUPPORTED, "absent q"),
    ):
        Verdict.finalise("c1", "MED:1", out, ABSTRACT).verify_against(ABSTRACT)


@pytest.mark.parametrize(
    "forged",
    [
        pytest.param({"evidence_span": Span(1, 5)}, id="shifted-span"),
        pytest.param({"evidence_span": Span(0, 10_000)}, id="out-of-range-span"),
        pytest.param({"evidence_quote": "aspirin cured every patient"}, id="span-over-different-text"),
        pytest.param(
            {
                "evidence_quote": "aspirin cured every patient",
                "evidence_status": EvidenceStatus.NEAR,
                "evidence_span": None,
                "negation": NegationCheck.NOT_RUN,
            },
            id="absent-claimed-near",
        ),
    ],
)
def test_verify_against_rejects_forged_spans(forged: dict[str, object]) -> None:
    honest = Verdict.finalise("c1", "MED:1", _out(Label.SUPPORTED, QUOTE), ABSTRACT, _clear)
    honest.verify_against(ABSTRACT, _clear)
    forgery = Verdict.model_validate(honest.model_dump() | forged)
    with pytest.raises(ValueError, match=r"stored evidence .* does not match the abstract"):
        forgery.verify_against(ABSTRACT, _clear)


def test_a_stored_negation_result_must_be_reproduced() -> None:
    honest = Verdict.finalise("c1", "MED:1", _out(Label.SUPPORTED, QUOTE), ABSTRACT)
    honest.verify_against(ABSTRACT)
    honest.verify_against(ABSTRACT, _negated)  # NOT_RUN can only lower the disposition
    forgery = Verdict.model_validate(honest.model_dump() | {"negation": "clear"})
    assert forgery.disposition is Disposition.PASSED
    with pytest.raises(ValueError, match="negation=clear cannot be re-checked"):
        forgery.verify_against(ABSTRACT)
    with pytest.raises(ValueError, match="stored negation=clear does not match the abstract"):
        forgery.verify_against(ABSTRACT, _negated)
    forgery.verify_against(ABSTRACT, _clear)  # an honest detector agreeing is the only way to PASSED


def test_verify_against_rejects_a_different_abstract() -> None:
    v = Verdict.finalise("c1", "MED:1", _out(Label.SUPPORTED, QUOTE), ABSTRACT)
    with pytest.raises(ValueError, match="does not match"):
        v.verify_against(CleanedText("Prefix. " + ABSTRACT))


def test_verdict_is_frozen() -> None:
    v = Verdict.finalise("c1", "MED:1", _out(Label.SUPPORTED, QUOTE), ABSTRACT)
    with pytest.raises(ValidationError, match="frozen"):
        v.semantic_label = Label.CONTRADICTED


def test_model_copy_cannot_bypass_validation() -> None:
    v = Verdict.finalise("c1", "MED:1", _out(Label.SUPPORTED, QUOTE), ABSTRACT)
    with pytest.raises(TypeError, match="finalise"):
        v.model_copy(update={"evidence_status": EvidenceStatus.ABSENT})
    assert v.model_copy() == v
