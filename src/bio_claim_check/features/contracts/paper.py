"""[RING:features/contracts] A retrieved paper, as every slice sees it.

Why: retrieval, the answerer, the verifier and the report must read the same abstract text. Only the
raw abstract is stored; the cleaned text is derived by `clean_abstract` on every access, so a stored
"cleaned" copy can never be forged or go stale. (`clean_abstract` is not idempotent on double-escaped
entities, so "re-clean and compare" would wrongly reject valid text.)
Bibliographic metadata (S06) is optional and defaulted, so fakes and old artifacts stay valid. Absence is
never evidence: `mesh_headings=None` means "not indexed yet", not "no Animals tag", and an empty
`publication_types` means "unknown", never "primary research" (ADR 0008).
`retracted` is a snapshot from the first fetch (ADR 0009); it is re-checked for cited papers in S12.
Must not: fetch anything, or rank or judge papers.

No LLM is involved in this module.
"""

from typing import Annotated

from pydantic import Field

from bio_claim_check.common.text import CleanedText, clean_abstract
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.verdict import NonBlankStr, ValidatedModel


class Paper(ValidatedModel):
    """One citable abstract. `abstract` is derived; it is never part of the stored model."""

    source_id: SourceId
    title: NonBlankStr
    year: Annotated[int, Field(strict=True, ge=1800, le=2200)] | None
    raw_abstract: str
    pmcid: NonBlankStr | None = None
    doi: NonBlankStr | None = None
    mesh_headings: tuple[NonBlankStr, ...] | None = None
    """MeSH descriptor names; None until MEDLINE indexes the paper (often months after publication)."""
    publication_types: tuple[NonBlankStr, ...] = ()
    """As the database lists them, e.g. ("Journal Article", "Review"); empty = unknown."""
    retracted: Annotated[bool, Field(strict=True)] = False
    open_access: Annotated[bool, Field(strict=True)] | None = None
    license: NonBlankStr | None = None

    @property
    def abstract(self) -> CleanedText:
        """The one text the model reads, the checks match and the report shows."""
        return clean_abstract(self.raw_abstract)
