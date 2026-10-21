"""The citable-source policy (ADR 0008) on fictional records in the live API's shape."""

from typing import Any

import pytest
from tests.support.europepmc import good_record, mixed_records

from bio_claim_check.features.retrieval.citable import (
    EXCLUDED_PUB_TYPES,
    QUERY_FILTERS,
    MalformedRecordError,
    RejectReason,
    is_citable,
    record_to_paper,
    validate_shape,
)

pytestmark = pytest.mark.unit


def _with(**changes: Any) -> dict[str, Any]:
    record = good_record()
    for k, v in changes.items():
        if v is None:
            record.pop(k, None)
        else:
            record[k] = v
    return record


def test_a_full_record_becomes_a_paper_with_every_field() -> None:
    paper = record_to_paper(good_record())
    assert paper.source_id == "MED:90000001"
    assert paper.year == 2023
    assert paper.pmcid == "PMC90000001"
    assert paper.doi == "10.5555/fictional.90000001"
    assert paper.mesh_headings == ("Animals", "Alzheimer Disease")
    assert paper.publication_types == ("Research Support, Non-U.S. Gov't", "Journal Article")
    assert (paper.retracted, paper.open_access, paper.license) == (False, True, "cc by")
    assert "<i>" not in paper.abstract
    assert "p < 0.01" in paper.abstract


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"source": "PPR"}, RejectReason.NOT_MED),
        ({"source": None}, RejectReason.NOT_MED),
        ({"pmid": None}, RejectReason.NO_PMID),
        ({"pmid": "PMC123"}, RejectReason.NO_PMID),
        ({"pmid": "١٢٣"}, RejectReason.NO_PMID),  # Unicode digits are not a PMID
        ({"title": "  "}, RejectReason.NO_TITLE),
        ({"title": None}, RejectReason.NO_TITLE),
        ({"abstractText": None}, RejectReason.NO_ABSTRACT),
        ({"abstractText": "\n "}, RejectReason.NO_ABSTRACT),
        ({"language": "fre"}, RejectReason.WRONG_LANGUAGE),
        ({"language": None}, RejectReason.WRONG_LANGUAGE),
        *[
            ({"pubTypeList": {"pubType": ["Journal Article", t]}}, RejectReason.EXCLUDED_TYPE)
            for t in EXCLUDED_PUB_TYPES
        ],
        ({"pubTypeList": {"pubType": ["LETTER"]}}, RejectReason.EXCLUDED_TYPE),  # compared casefolded
    ],
)
def test_reject_reasons(changes: dict[str, Any], reason: RejectReason) -> None:
    assert is_citable(_with(**changes)) is reason
    with pytest.raises(ValueError, match="not citable"):
        record_to_paper(_with(**changes))


def test_reviews_are_citable() -> None:
    assert is_citable(_with(pubTypeList={"pubType": ["Review"]})) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"pubTypeList": {"pubType": ["Journal Article", "Retracted Publication"]}},
        {"pubTypeList": {"pubType": ["retracted publication"]}},
        {"commentCorrectionList": {"commentCorrection": [{"type": "Retraction in", "reference": "1"}]}},
    ],
)
def test_retracted_papers_are_kept_and_marked(changes: dict[str, Any]) -> None:
    assert record_to_paper(_with(**changes)).retracted is True


def test_other_corrections_do_not_mark_a_retraction() -> None:
    record = _with(commentCorrectionList={"commentCorrection": [{"type": "Erratum in", "reference": "1"}]})
    assert record_to_paper(record).retracted is False


def test_absent_metadata_is_unknown_not_negative() -> None:
    paper = record_to_paper(
        _with(meshHeadingList=None, pubTypeList=None, isOpenAccess=None, license=None, pmcid=None, doi=None)
    )
    assert paper.mesh_headings is None
    assert paper.publication_types == ()
    assert (paper.open_access, paper.license, paper.pmcid, paper.doi) == (None, None, None, None)


@pytest.mark.parametrize(("raw", "year"), [("2023", 2023), ("in press", None), ("1700", None), (None, None)])
def test_year(raw: str | None, year: int | None) -> None:
    assert record_to_paper(_with(pubYear=raw)).year == year


@pytest.mark.parametrize(
    "changes",
    [
        {"pmid": 90000001},
        {"title": ["a"]},
        {"pubTypeList": {"pubType": "Journal Article"}},  # a bare string: not the observed shape
        {"pubTypeList": ["Journal Article"]},
        {"pubTypeList": {"pubType": [1]}},
        {"meshHeadingList": {"meshHeading": ["Animals"]}},
        {"meshHeadingList": {"meshHeading": [{"descriptorName": 3}]}},
        {"commentCorrectionList": {"commentCorrection": [{"reference": "1"}]}},
        {"isOpenAccess": True},
    ],
)
def test_unexpected_shapes_are_malformed(changes: dict[str, Any]) -> None:
    with pytest.raises(MalformedRecordError):
        validate_shape(_with(**changes))


def test_every_fixture_record_has_a_valid_shape() -> None:
    for record in mixed_records():
        validate_shape(record)


def test_query_filters_name_every_excluded_type() -> None:
    assert QUERY_FILTERS.startswith("SRC:MED AND HAS_ABSTRACT:y AND LANG:eng ")
    for t in EXCLUDED_PUB_TYPES:
        assert f'NOT PUB_TYPE:"{t}"' in QUERY_FILTERS
