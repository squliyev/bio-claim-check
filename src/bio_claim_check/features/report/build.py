"""[RING:features/report] Build a report from the outcomes of one run.

Why: one constructor for the report, so the use case cannot assemble one by hand in a different order.
Must not: drop, merge or deduplicate outcomes; two claims citing one source are two pairs.

No LLM is involved in this module.
"""

from collections.abc import Mapping

from bio_claim_check.features.contracts.answer import Answer
from bio_claim_check.features.contracts.finding import Finding
from bio_claim_check.features.contracts.ids import ClaimId, SourceId
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.verdict import PairOutcome
from bio_claim_check.features.report.models import ClaimReport, Provenance, Report, RunModels, pair_report


def build_report(
    *,
    provenance: Provenance,
    answer: Answer,
    papers: tuple[Paper, ...],
    findings: tuple[Finding, ...],
    outcomes: Mapping[ClaimId, Mapping[SourceId, PairOutcome]],
    models: RunModels | None,
) -> Report:
    """Every claim needs exactly one outcome per cited source; anything missing or extra raises."""
    if extra := outcomes.keys() - {c.id for c in answer.claims}:
        raise ValueError(f"outcomes for claims not in the answer: {sorted(extra)}")
    claims: list[ClaimReport] = []
    for claim in answer.claims:
        by_source = outcomes.get(claim.id, {})
        if set(by_source) != set(claim.cites):
            raise ValueError(f"claim {claim.id}: outcomes must cover exactly its cited sources")
        claims.append(ClaimReport(claim=claim, pairs=tuple(pair_report(by_source[s]) for s in claim.cites)))
    return Report(
        provenance=provenance,
        question=answer.question,
        mode=answer.mode,
        papers=papers,
        claims=tuple(claims),
        findings=findings,
        models=models,
    )
