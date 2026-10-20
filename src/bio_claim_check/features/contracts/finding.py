"""[RING:features/contracts] A finding from a deterministic check on an answer.

Why: the checks slice produces findings and the report slice shows them; slices never import each
other, so the shape lives here.
Must not: carry a judgement of meaning; a finding states a checkable fact (e.g. "this citation was
never retrieved").

No LLM is involved in this module.
"""

from enum import StrEnum

from bio_claim_check.features.contracts.ids import ClaimId, SourceId
from bio_claim_check.features.contracts.verdict import NonBlankStr, ValidatedModel


class FindingKind(StrEnum):
    """What a deterministic check found."""

    INVENTED_CITATION = "invented_citation"


class Finding(ValidatedModel):
    """One fact a check established about one (claim, source) pair."""

    kind: FindingKind
    claim_id: ClaimId
    source_id: SourceId
    detail: NonBlankStr
