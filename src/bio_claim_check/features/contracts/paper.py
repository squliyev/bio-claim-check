"""[RING:features/contracts] A retrieved paper, as every slice sees it.

Why: retrieval, the answerer, the verifier and the report must read the same abstract text. Only the
raw abstract is stored; the cleaned text is derived by `clean_abstract` on every access, so a stored
"cleaned" copy can never be forged or go stale. (`clean_abstract` is not idempotent on double-escaped
entities, so "re-clean and compare" would wrongly reject valid text.)
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

    @property
    def abstract(self) -> CleanedText:
        """The one text the model reads, the checks match and the report shows."""
        return clean_abstract(self.raw_abstract)
