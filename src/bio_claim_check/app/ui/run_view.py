"""[RING:app/ui] Turns a loaded run into what the page shows, with every text already HTML-escaped.

Why: the page renders some of this with `unsafe_allow_html` (the highlighted evidence), and the texts
come from papers, users and models. Escaping in one pure place means the page never decides what is
safe (I81). The evidence is marked only where code agrees with the stored span: the span fits the abstract
and `locate_quote` finds the stored quote exactly there. Otherwise the abstract is shown plain.
Must not: import streamlit, re-judge a pair, compute a rate, or return a text that is not escaped.
No LLM is involved in this module.
"""

import html
from dataclasses import dataclass
from typing import Literal

from bio_claim_check.app.usecases.published_run import PublishedRun
from bio_claim_check.app.usecases.run_dev import DevRunRecord
from bio_claim_check.common.text import CleanedText, Span, locate_quote
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.report.models import (
    ClaimCheck,
    ClaimReport,
    FailurePair,
    ModelUse,
    NotRetrievedPair,
    Report,
    VerdictPair,
)


def esc(text: str) -> str:
    """HTML-escaped text, quotes included."""
    return html.escape(text, quote=True)


@dataclass(frozen=True, slots=True)
class PairView:
    """One (claim, source) pair. Every `*_html` field is escaped; the others are enum values or ids."""

    source_id_html: str
    title_html: str
    year: str
    disposition: str
    outcome: Literal["verdict", "failure", "citation_not_retrieved"]
    label: str | None
    overstated_reason: str | None
    reason_html: str | None
    quote_html: str | None
    evidence_status: str | None
    abstract_html: str
    highlighted: bool
    failure: str | None


@dataclass(frozen=True, slots=True)
class ClaimView:
    claim_id_html: str
    text_html: str
    disposition: str
    pairs: tuple[PairView, ...]


@dataclass(frozen=True, slots=True)
class RunView:
    """A run or a check, ready to render."""

    command: str
    provenance: str
    notice_html: str
    heading_html: str
    record_html: str
    models_html: tuple[str, ...]
    same_family_warning: bool
    claims: tuple[ClaimView, ...]
    findings_html: tuple[str, ...]


def highlight(abstract: CleanedText, quote: str | None, span: Span | None) -> tuple[str, bool]:
    """The escaped abstract, with `<mark>` around the evidence only if the span fits and the quote is
    found exactly there; otherwise the whole abstract escaped and False."""
    if quote is None or span is None or span.end > len(abstract) or locate_quote(quote, abstract) != span:
        return esc(abstract), False
    before, inside, after = abstract[: span.start], abstract[span.start : span.end], abstract[span.end :]
    return f"{esc(before)}<mark>{esc(inside)}</mark>{esc(after)}", True


def view(run: PublishedRun) -> RunView:
    """The view of a published run or check."""
    artifact = run.artifact
    if isinstance(artifact, ClaimCheck):
        return view_check(artifact, run)
    return view_report(artifact.report if isinstance(artifact, DevRunRecord) else artifact, run)


def view_report(report: Report, run: PublishedRun) -> RunView:
    papers = {p.source_id: p for p in report.papers}
    models = report.models
    return RunView(
        command=run.manifest.command,
        provenance=report.provenance,
        notice_html=esc(report.notice),
        heading_html=esc(report.question),
        record_html=_record(run),
        models_html=()
        if models is None
        else (_model("answerer", models.answerer), _model("verifier", models.verifier)),
        same_family_warning=models is not None and models.same_family,
        claims=tuple(_claim(c, papers) for c in report.claims),
        findings_html=tuple(
            f"{esc(f.kind.value)}: {esc(f.claim_id)}: {esc(f.detail)}" for f in report.findings
        ),
    )


def view_check(check: ClaimCheck, run: PublishedRun) -> RunView:
    return RunView(
        command=run.manifest.command,
        provenance=check.provenance,
        notice_html=esc(check.notice),
        heading_html=esc(check.claim.claim.text),
        record_html=_record(run),
        models_html=() if check.verifier is None else (_model("verifier", check.verifier),),
        same_family_warning=False,
        claims=(_claim(check.claim, {check.paper.source_id: check.paper}),),
        findings_html=(),
    )


def _record(run: PublishedRun) -> str:
    m = run.manifest
    return esc(f"run {run.run_id} · {m.command} · {m.provenance} · bio-claim-check {m.package_version}")


def _model(role: str, use: ModelUse) -> str:
    return esc(f"{role}: {use.deployment} ({use.family.value})")


def _claim(claim: ClaimReport, papers: dict[str, Paper]) -> ClaimView:
    return ClaimView(
        claim_id_html=esc(claim.claim.id),
        text_html=esc(claim.claim.text),
        disposition=claim.disposition.value,
        pairs=tuple(_pair(p, papers.get(p.result.source_id)) for p in claim.pairs),
    )


def _pair(pair: VerdictPair | FailurePair | NotRetrievedPair, paper: Paper | None) -> PairView:
    abstract_html, highlighted = ("", False)
    label = reason = quote = status = reason_kind = failure = None
    if isinstance(pair, VerdictPair):
        v = pair.verdict
        label, status = v.semantic_label.value, v.evidence_status.value
        reason_kind = None if v.overstated_reason is None else v.overstated_reason.value
        reason = esc(v.reason)
        quote = None if v.evidence_quote is None else esc(v.evidence_quote)
        if paper is not None:
            abstract_html, highlighted = highlight(paper.abstract, v.evidence_quote, v.evidence_span)
    else:
        failure = pair.failure.kind.value if isinstance(pair, FailurePair) else "citation_not_retrieved"
        if paper is not None:
            abstract_html = esc(paper.abstract)
    return PairView(
        source_id_html=esc(pair.result.source_id),
        title_html="" if paper is None else esc(paper.title),
        year="" if paper is None or paper.year is None else str(paper.year),
        disposition=pair.disposition.value,
        outcome=pair.outcome,
        label=label,
        overstated_reason=reason_kind,
        reason_html=reason,
        quote_html=quote,
        evidence_status=status,
        abstract_html=abstract_html,
        highlighted=highlighted,
        failure=failure,
    )
