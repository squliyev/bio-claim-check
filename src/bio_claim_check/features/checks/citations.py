"""[RING:features/checks] Citations to papers that were never retrieved.

Why: an answer may only cite what retrieval returned. A citation outside that set is invented (or at
best unverifiable), whatever the claim says.
Must not: judge the claim; the pair is still reported as FLAGGED (CitationNotRetrieved) by the report.

No LLM is involved in this module.
"""

from collections.abc import Collection

from bio_claim_check.features.contracts.answer import Answer
from bio_claim_check.features.contracts.finding import Finding, FindingKind
from bio_claim_check.features.contracts.ids import SourceId


def invented_citations(answer: Answer, retrieved: Collection[SourceId]) -> tuple[Finding, ...]:
    """One finding per (claim, cited source) not in `retrieved`, in claim then citation order."""
    return tuple(
        Finding(
            kind=FindingKind.INVENTED_CITATION,
            claim_id=claim.id,
            source_id=source_id,
            detail=f"{source_id} is cited but was not among the retrieved papers",
        )
        for claim in answer.claims
        for source_id in claim.cites
        if source_id not in retrieved
    )
