"""[RING:features/retrieval] What counts as a citable paper, and how a Europe PMC record becomes a `Paper`.

Why: the query filters ask Europe PMC for MEDLINE/PubMed-indexed English abstracts without notices or
opinion pieces, but the query is the user's text verbatim, so `a) OR (b` can escape them. This module
re-checks every returned record against the same policy; the post-filter, not the query, is the guarantee
(ADR 0008, invariant I35). Record shapes are pinned to what the live API returned (probed 2026-10-20):
an unexpected type is a malformed response, never a guess.
Must not: do I/O, rank papers, or call anything "peer-reviewed" (MEDLINE indexing is not peer review).

No LLM is involved in this module.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import cast

from bio_claim_check.common.errors import BccError
from bio_claim_check.features.contracts.paper import Paper

EXCLUDED_PUB_TYPES: tuple[str, ...] = (
    "Retraction of Publication",
    "Published Erratum",
    "Comment",
    "Editorial",
    "Letter",
    "News",
)
"""Notices and opinion, not findings. Reviews are kept. Spellings checked by `make live` (ADR 0008)."""

QUERY_FILTERS = "SRC:MED AND HAS_ABSTRACT:y AND LANG:eng " + " ".join(
    f'NOT PUB_TYPE:"{t}"' for t in EXCLUDED_PUB_TYPES
)
"""Appended to the user's query as `(<query>) AND <filters>`. An optimisation; `is_citable` is the rule."""

RETRACTED_PUB_TYPE = "Retracted Publication"
RETRACTION_NOTICE_TYPE = "Retraction in"

_EXCLUDED = frozenset(t.casefold() for t in EXCLUDED_PUB_TYPES)  # the API capitalises; the filter does not

type Record = Mapping[str, object]


class RejectReason(StrEnum):
    """Why a returned record is not citable. Counted and logged, never silently dropped."""

    NOT_MED = "not_med"
    NO_PMID = "no_pmid"
    NO_TITLE = "no_title"
    NO_ABSTRACT = "no_abstract"
    WRONG_LANGUAGE = "wrong_language"
    EXCLUDED_TYPE = "excluded_type"
    DUPLICATE = "duplicate"


class MalformedRecordError(BccError, ValueError):
    """A record field has a type the API has not been seen to return."""

    code = "retrieval.malformed_record"


def _opt_str(record: Record, field: str) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise MalformedRecordError(f"{field}: expected a string, got {type(value).__name__}")
    return value.strip() or None


def _wrapped_list(record: Record, outer: str, inner: str) -> list[object] | None:
    """`{"outer": {"inner": [...]}}` → the list; absent → None."""
    wrapper = record.get(outer)
    if wrapper is None:
        return None
    if not isinstance(wrapper, Mapping):
        raise MalformedRecordError(f"{outer}: expected an object")
    items = cast(Record, wrapper).get(inner)  # parsed JSON: keys are str
    if not isinstance(items, list):
        raise MalformedRecordError(f"{outer}.{inner}: expected a list")
    return cast(list[object], items)  # elements are checked by each caller


def _str_items(record: Record, outer: str, inner: str) -> tuple[str, ...] | None:
    items = _wrapped_list(record, outer, inner)
    if items is None:
        return None
    if not all(isinstance(i, str) for i in items):
        raise MalformedRecordError(f"{outer}.{inner}: expected strings")
    return tuple(s for i in items if isinstance(i, str) and (s := i.strip()))


def _object_field(record: Record, outer: str, inner: str, field: str) -> tuple[str, ...] | None:
    items = _wrapped_list(record, outer, inner)
    if items is None:
        return None
    found: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise MalformedRecordError(f"{outer}.{inner}: expected objects")
        value = cast(Record, item).get(field)
        if not isinstance(value, str):
            raise MalformedRecordError(f"{outer}.{inner}[].{field}: expected a string")
        if value.strip():
            found.append(value.strip())
    return tuple(found)


def publication_types(record: Record) -> tuple[str, ...]:
    return _str_items(record, "pubTypeList", "pubType") or ()


def mesh_headings(record: Record) -> tuple[str, ...] | None:
    return _object_field(record, "meshHeadingList", "meshHeading", "descriptorName")


def is_retracted(record: Record) -> bool:
    """A "Retracted Publication" type, or a "Retraction in" link to the retraction notice."""
    corrections = _object_field(record, "commentCorrectionList", "commentCorrection", "type") or ()
    types = {t.casefold() for t in publication_types(record)}
    return RETRACTED_PUB_TYPE.casefold() in types or RETRACTION_NOTICE_TYPE in corrections


def is_citable(record: Record) -> RejectReason | None:
    """None if the record is a citable paper, else the first reason it is not.

    Raises:
        MalformedRecordError: a field has an unexpected type (the whole response is then untrusted).
    """
    if _opt_str(record, "source") != "MED":
        return RejectReason.NOT_MED
    pmid = _opt_str(record, "pmid")
    if pmid is None or not (pmid.isascii() and pmid.isdigit()):
        return RejectReason.NO_PMID
    if _opt_str(record, "title") is None:
        return RejectReason.NO_TITLE
    if _opt_str(record, "abstractText") is None:
        return RejectReason.NO_ABSTRACT
    if _opt_str(record, "language") != "eng":
        return RejectReason.WRONG_LANGUAGE
    if any(t.casefold() in _EXCLUDED for t in publication_types(record)):
        return RejectReason.EXCLUDED_TYPE
    return None


def validate_shape(record: Record) -> None:
    """Touch every field `record_to_paper` reads, so a malformed record fails before anything is cached."""
    for field in ("id", "source", "pmid", "pmcid", "doi", "title", "pubYear", "abstractText", "language"):
        _opt_str(record, field)
    for field in ("isOpenAccess", "license"):
        _opt_str(record, field)
    publication_types(record)
    mesh_headings(record)
    is_retracted(record)


def _year(record: Record) -> int | None:
    text = _opt_str(record, "pubYear")
    if text is None or not (text.isascii() and text.isdigit()):
        return None
    year = int(text)
    return year if 1800 <= year <= 2200 else None


def _open_access(record: Record) -> bool | None:
    return {"Y": True, "N": False}.get(_opt_str(record, "isOpenAccess") or "")


def record_to_paper(record: Record) -> Paper:
    """The `Paper` for a record that `is_citable` accepted. Identity is always `MED:<pmid>` (ADR 0008)."""
    if (reason := is_citable(record)) is not None:
        raise ValueError(f"not citable: {reason}")
    return Paper(
        source_id=f"MED:{_opt_str(record, 'pmid')}",
        title=_opt_str(record, "title") or "",
        year=_year(record),
        raw_abstract=_opt_str(record, "abstractText") or "",
        pmcid=_opt_str(record, "pmcid"),
        doi=_opt_str(record, "doi"),
        mesh_headings=mesh_headings(record),
        publication_types=publication_types(record),
        retracted=is_retracted(record),
        open_access=_open_access(record),
        license=_opt_str(record, "license"),
    )
