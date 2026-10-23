"""[RING:features/contracts] A finding from a deterministic check on an answer.

Why: the checks slice produces findings and the report slice shows them; slices never import each
other, so the shape lives here.
Must not: carry a judgement of meaning; a finding states a checkable fact (e.g. "this citation was
never retrieved", "this claim opens with a reference to nothing inside it"). A finding is about one
claim, and about one cited source only when the check is about that source.

No LLM is involved in this module.
"""

from enum import StrEnum
from typing import Self

from pydantic import model_validator

from bio_claim_check.common.models import NonBlankStr, ValidatedModel
from bio_claim_check.features.contracts.ids import ClaimId, SourceId


class FindingKind(StrEnum):
    """What a deterministic check found."""

    INVENTED_CITATION = "invented_citation"
    DANGLING_REFERENCE = "dangling_reference"


_ABOUT_A_SOURCE = frozenset({FindingKind.INVENTED_CITATION})


class Finding(ValidatedModel):
    """One fact a check established about a claim, or about one of its cited sources."""

    kind: FindingKind
    claim_id: ClaimId
    source_id: SourceId | None
    detail: NonBlankStr

    @model_validator(mode="after")
    def _source_matches_kind(self) -> Self:
        if (self.source_id is not None) != (self.kind in _ABOUT_A_SOURCE):
            need = "needs" if self.kind in _ABOUT_A_SOURCE else "must not have"
            raise ValueError(f"source_id: a {self.kind.value} finding {need} a source")
        return self
