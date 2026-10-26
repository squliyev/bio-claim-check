"""[RING:app/usecases] Answer one question and check every claim against the paper it cites.

Why: this is the product flow: retrieve → answer → deterministic checks → verify each (claim, source)
pair → report. It distrusts every port: a source that returns too many or duplicate papers, an answer
that does not echo its question, or a verdict whose evidence does not re-locate in its abstract raises
instead of becoming a number. A cite outside the retrieved set is never sent to the verifier; it is
recorded as CitationNotRetrieved (FLAGGED) and as a finding (invariant I18). Claims that refer to
something outside themselves are flagged after the invented citations; they are still verified.
Stage events (`retrieve`, `answer`, `verify`) go to the ports' emitter when one is given (S11).
`check_answer` is everything after retrieval, shared with the dev path (`run_dev`, S12a), so live and dev
answers are checked by one flow. A free question whose search returns a sealed test-split paper is
refused before the answerer sees anything (I84, H1); it fails closed instead of filtering, because a
filter would change which papers a run answers from (that is S15's call).
Must not: do I/O (the caller writes the report), catch errors to keep going, or import the container,
the driving adapters or infrastructure: it receives its ports in `RunPorts` (S05b).
"""

from dataclasses import dataclass

from bio_claim_check.app.usecases.check_claim import HeldOutSourceError
from bio_claim_check.common.errors import BccError
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.stage_events import stage
from bio_claim_check.features.answer.base_answerer import BaseAnswerer
from bio_claim_check.features.checks.citations import invented_citations
from bio_claim_check.features.checks.self_containment import dangling_claims
from bio_claim_check.features.contracts.ids import ClaimId, SourceId
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.rulepack import RulePack
from bio_claim_check.features.contracts.verdict import CitationNotRetrieved, PairOutcome, Verdict
from bio_claim_check.features.report.build import build_report
from bio_claim_check.features.report.models import Provenance, Report, RunModels
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.verify.base_verifier import BaseVerifier


class RunInputError(BccError):
    """The question is blank or `k` is not a positive int."""

    code = "run.input"


@dataclass(frozen=True, slots=True)
class RunPorts:
    """Everything one run needs, chosen by the composition root. `rules_sha256` is the hash of the rule
    pack's file bytes, for the run manifest; `emitter` receives the stage events (S11). `models` names the
    answerer and verifier of a live run and is `None` for a fake one (I71). `closed_ids` are the sealed
    test-split ids a free question must not retrieve; required, so no builder forgets it (I84)."""

    literature: BaseLiteratureSource
    answerer: BaseAnswerer
    verifier: BaseVerifier
    rules: RulePack
    provenance: Provenance
    rules_sha256: str
    closed_ids: frozenset[SourceId]
    models: RunModels | None = None
    emitter: EventEmitter | None = None


def run_question(c: RunPorts, question: str, mode: AnswerMode, *, k: int) -> Report:
    """Run the whole flow for one question; `k` is the number of papers to retrieve (≥ 1)."""
    if type(k) is not int or k < 1:
        raise RunInputError(f"k must be an integer ≥ 1, got {k!r}")
    if not question.strip():
        raise RunInputError("the question must not be blank")

    with stage(c.emitter, "retrieve"):
        papers = c.literature.search(question, limit=k)
    if len(papers) > k:
        raise ValueError(f"literature source returned {len(papers)} papers for limit={k}")
    if sealed := {p.source_id for p in papers} & c.closed_ids:
        raise HeldOutSourceError(sealed)
    return check_answer(c, question, papers, mode)


def check_answer(c: RunPorts, question: str, papers: tuple[Paper, ...], mode: AnswerMode) -> Report:
    """Answer from exactly `papers`, run the deterministic checks, verify each pair, build the report."""
    by_id = {p.source_id: p for p in papers}
    if len(by_id) != len(papers):
        raise ValueError("literature source returned duplicate source ids")

    with stage(c.emitter, "answer"):
        answer = c.answerer.answer(question, papers, mode)
    if (answer.question, answer.mode) != (question, mode):
        raise ValueError("answerer returned an answer to a different question or mode")

    outcomes: dict[ClaimId, dict[SourceId, PairOutcome]] = {}
    with stage(c.emitter, "verify"):
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
        findings=(*invented_citations(answer, by_id.keys()), *dangling_claims(answer)),
        outcomes=outcomes,
        models=c.models,
    )
