"""`Paper`, `Answer`, `Finding` and `CitationNotRetrieved` (S05 contracts; I18)."""

import pytest
from pydantic import ValidationError

from bio_claim_check.common.text import clean_abstract
from bio_claim_check.features.contracts.answer import Answer
from bio_claim_check.features.contracts.finding import Finding, FindingKind
from bio_claim_check.features.contracts.labels import AnswerMode, Disposition, FailureKind
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.verdict import (
    CitationNotRetrieved,
    Claim,
    VerifierFailure,
    claim_disposition,
)

pytestmark = pytest.mark.unit

RAW = "<p>In <i>APP/PS1</i> mice, X reduced plaque by 10<sup>2</sup> (p &lt; 0.01).</p>"


def _paper(**update: object) -> Paper:
    fields: dict[str, object] = {"source_id": "FAKE:1", "title": "T", "year": 2021, "raw_abstract": RAW}
    return Paper.model_validate(fields | update)


def test_paper_abstract_is_derived_on_every_access() -> None:
    paper = _paper()
    assert paper.abstract == clean_abstract(RAW) == "In APP/PS1 mice, X reduced plaque by 10^2 (p < 0.01)."
    before = (paper.model_dump(), hash(paper))
    _ = paper.abstract
    assert (paper.model_dump(), hash(paper)) == before


def test_paper_dump_holds_only_the_raw_abstract() -> None:
    dumped = _paper().model_dump(mode="json")
    assert "abstract" not in dumped
    assert Paper.model_validate_json(_paper().model_dump_json()) == _paper()


def test_paper_rejects_an_injected_cleaned_abstract() -> None:
    with pytest.raises(ValidationError, match="abstract"):
        _paper(abstract="a forged cleaned text")


@pytest.mark.parametrize(
    "update",
    [{"source_id": "not an id"}, {"title": "  "}, {"year": 1799}, {"year": "2021"}, {"year": True}],
)
def test_paper_rejects_bad_fields(update: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _paper(**update)


def test_paper_year_may_be_unknown() -> None:
    assert _paper(year=None).year is None


def test_paper_refuses_an_unvalidated_copy() -> None:
    with pytest.raises(TypeError):
        _paper().model_copy(update={"raw_abstract": "x"})


CLAIM = Claim(id="c1", text="X works.", cites=("FAKE:1",))


def test_answer_with_no_claims_is_an_abstention() -> None:
    assert Answer(question="q?", mode=AnswerMode.STRICT, claims=()).claims == ()


def test_answer_rejects_duplicate_claim_ids() -> None:
    with pytest.raises(ValidationError, match="unique"):
        Answer(question="q?", mode=AnswerMode.STRICT, claims=(CLAIM, CLAIM))


@pytest.mark.parametrize("question", ["", "   ", "\n"])
def test_answer_rejects_a_blank_question(question: str) -> None:
    with pytest.raises(ValidationError):
        Answer(question=question, mode=AnswerMode.STRICT, claims=())


def test_answer_mode_values_are_snake_case() -> None:
    assert [m.value for m in AnswerMode] == ["strict", "over_eager"]


def test_finding_requires_detail() -> None:
    with pytest.raises(ValidationError):
        Finding(kind=FindingKind.INVENTED_CITATION, claim_id="c1", source_id="FAKE:9", detail=" ")


def test_citation_not_retrieved_is_flagged() -> None:
    assert CitationNotRetrieved(claim_id="c1", source_id="FAKE:9").disposition is Disposition.FLAGGED


def test_claim_disposition_ranks_not_retrieved_as_flagged() -> None:
    claim = Claim(id="c1", text="X works.", cites=("FAKE:1", "FAKE:9"))
    outcomes = {
        "FAKE:1": VerifierFailure(claim_id="c1", source_id="FAKE:1", kind=FailureKind.PROVIDER_ERROR),
        "FAKE:9": CitationNotRetrieved(claim_id="c1", source_id="FAKE:9"),
    }
    assert claim_disposition(claim, outcomes) is Disposition.FLAGGED


@pytest.mark.parametrize(("claim_id", "source_id"), [("c2", "FAKE:9"), ("c1", "FAKE:8")])
def test_claim_disposition_rejects_a_misfiled_not_retrieved(claim_id: str, source_id: str) -> None:
    claim = Claim(id="c1", text="X works.", cites=("FAKE:9",))
    with pytest.raises(ValueError, match="belongs to"):
        claim_disposition(claim, {"FAKE:9": CitationNotRetrieved(claim_id=claim_id, source_id=source_id)})
