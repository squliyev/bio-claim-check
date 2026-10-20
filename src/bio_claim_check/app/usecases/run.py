"""[RING:app/usecases] Answer one question and check every claim against the paper it cites.

Why: this is the product flow: retrieve → answer → deterministic checks → verify each (claim, source)
pair → report. It distrusts every port: a source that returns too many or duplicate papers, an answer
that does not echo its question, or a verdict whose evidence does not re-locate in its abstract raises
instead of becoming a number. A cite outside the retrieved set is never sent to the verifier; it is
recorded as CitationNotRetrieved (FLAGGED) and as a finding (invariant I18).
Must not: do I/O (the caller writes the report) or catch errors to keep going.
"""

from bio_claim_check.app.container import Container
from bio_claim_check.features.checks.citations import invented_citations
from bio_claim_check.features.contracts.ids import ClaimId, SourceId
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.contracts.verdict import CitationNotRetrieved, PairOutcome, Verdict
from bio_claim_check.features.report.build import build_report
from bio_claim_check.features.report.models import Report


def run_question(c: Container, question: str, mode: AnswerMode, *, k: int) -> Report:
    """Run the whole flow for one question; `k` is the number of papers to retrieve (≥ 1)."""
    if type(k) is not int or k < 1:
        raise ValueError(f"k must be an integer ≥ 1, got {k!r}")
    if not question.strip():
        raise ValueError("question must not be blank")

    papers = c.literature.search(question, limit=k)
    if len(papers) > k:
        raise ValueError(f"literature source returned {len(papers)} papers for limit={k}")
    by_id = {p.source_id: p for p in papers}
    if len(by_id) != len(papers):
        raise ValueError("literature source returned duplicate source ids")

    answer = c.answerer.answer(question, papers, mode)
    if (answer.question, answer.mode) != (question, mode):
        raise ValueError("answerer returned an answer to a different question or mode")

    outcomes: dict[ClaimId, dict[SourceId, PairOutcome]] = {}
    for claim in answer.claims:
        per_source: dict[SourceId, PairOutcome] = {}
        for source_id in claim.cites:
            paper = by_id.get(source_id)
            if paper is None:
                per_source[source_id] = CitationNotRetrieved(claim_id=claim.id, source_id=source_id)
                continue
            outcome = c.verifier.verify(claim, paper, c.rules)
            if isinstance(outcome, Verdict):
                outcome.verify_against(paper.abstract)
            per_source[source_id] = outcome
        outcomes[claim.id] = per_source

    return build_report(
        provenance=c.provenance,
        answer=answer,
        papers=papers,
        findings=invented_citations(answer, by_id.keys()),
        outcomes=outcomes,
    )
