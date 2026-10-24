"""[RING:features/contracts] What the verifier and the code checks made of one scored (claim, source) item.

Why: the challenge set (S12b) and the trap set (S13) both record one outcome per item, and the benchmark
(S16) reads both. Slices never import each other, so the shared record lives here. It replaced
`features.bench.challenge.ChallengeOutcome` (same fields, same bytes; that name is kept as an alias).
Must not: hold a quote or reason text (ADR 0008: committed results carry labels and statuses only), or
score anything; scoring belongs to the slice that owns the item set.

No LLM is involved in this module.
"""

from typing import Self

from pydantic import model_validator

from bio_claim_check.common.models import ValidatedModel
from bio_claim_check.features.contracts.ids import ClaimId
from bio_claim_check.features.contracts.labels import (
    Disposition,
    EvidenceStatus,
    FailureKind,
    Label,
    NegationCheck,
    OverstatedReason,
)
from bio_claim_check.features.contracts.verdict import Verdict, VerifierFailure


class PairOutcome(ValidatedModel):
    """One item's outcome. No quote and no reason text."""

    id: ClaimId
    label: Label | None
    reason: OverstatedReason | None
    evidence_status: EvidenceStatus | None
    negation: NegationCheck | None
    disposition: Disposition
    failure_kind: FailureKind | None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        failed = self.failure_kind is not None
        judged = (self.label, self.evidence_status, self.negation)
        if failed and (any(v is not None for v in judged) or self.reason is not None):
            raise ValueError("a failed item has no label, reason, evidence or negation")
        if failed != (self.disposition is Disposition.FAILED):
            raise ValueError("disposition: failed if and only if failure_kind is set")
        if not failed and any(v is None for v in judged):
            raise ValueError("a judged item has a label, evidence status and negation check")
        return self

    @classmethod
    def of(cls, item_id: str, result: Verdict | VerifierFailure) -> Self:
        """The outcome of one verifier result, keyed by the item (not the claim id the verifier saw)."""
        if isinstance(result, VerifierFailure):
            return cls(
                id=item_id,
                label=None,
                reason=None,
                evidence_status=None,
                negation=None,
                disposition=Disposition.FAILED,
                failure_kind=result.kind,
            )
        return cls(
            id=item_id,
            label=result.semantic_label,
            reason=result.overstated_reason,
            evidence_status=result.evidence_status,
            negation=result.negation,
            disposition=result.disposition,
            failure_kind=None,
        )
