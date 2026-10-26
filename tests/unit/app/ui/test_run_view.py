"""I81: every text the UI renders is escaped, and the evidence is marked only where code agrees with it."""

from pathlib import Path
from typing import Any, cast

import pytest

from bio_claim_check.app.container import fake_check_claims, read_published_files
from bio_claim_check.app.recorded import record_check, record_question
from bio_claim_check.app.ui.run_view import PairView, RunView, highlight, view, view_check, view_report
from bio_claim_check.app.usecases.published_run import PublishedRun, load_published
from bio_claim_check.common.text import CleanedText, Span, clean_abstract, locate_quote
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.report.models import ClaimCheck, Report

HOSTILE = "<script>alert(1)</script> & \"q\" 'a'"
DERIVED = frozenset({"disposition", "pair_counts", "claim_counts", "notice", "same_family"})


def _published(tmp_path: Path, run_id: str) -> PublishedRun:
    return load_published(run_id, *read_published_files(tmp_path, run_id))


def _question(tmp_path: Path) -> PublishedRun:
    run_id = record_question(
        "Does OS-912 help?", AnswerMode.OVER_EAGER, 3, settings=None, var_dir=tmp_path
    ).run_id
    return _published(tmp_path, run_id)


def _check(tmp_path: Path) -> PublishedRun:
    run_id = record_check(fake_check_claims()[0], settings=None, var_dir=tmp_path).run_id
    return _published(tmp_path, run_id)


def _strip(data: object) -> object:
    """A dump without derived fields, so an edited copy re-derives them on validation."""
    if isinstance(data, dict):
        items = cast("dict[str, object]", data).items()
        return {k: _strip(v) for k, v in items if k not in DERIVED}
    if isinstance(data, list):
        return [_strip(v) for v in cast("list[object]", data)]
    return data


def _all_text(run: RunView) -> list[str]:
    texts = [run.notice_html, run.heading_html, run.record_html, *run.models_html, *run.findings_html]
    for claim in run.claims:
        texts += [claim.claim_id_html, claim.text_html]
        for pair in claim.pairs:
            texts += [pair.source_id_html, pair.title_html, pair.abstract_html]
            texts += [t for t in (pair.reason_html, pair.quote_html) if t is not None]
    return texts


def _pairs(run: RunView) -> list[PairView]:
    return [p for c in run.claims for p in c.pairs]


def test_a_fake_run_shows_every_claim_and_pair_with_its_disposition(tmp_path: Path) -> None:
    run = _question(tmp_path)
    report = run.report
    assert report is not None
    shown = view(run)
    assert shown.command == "run"
    assert shown.provenance == "fake"
    assert shown.notice_html == report.notice
    assert [c.disposition for c in shown.claims] == [c.disposition.value for c in report.claims]
    expected = [p.disposition.value for c in report.claims for p in c.pairs]
    assert [p.disposition for p in _pairs(shown)] == expected
    assert len(shown.findings_html) == len(report.findings)
    assert shown.models_html == ()
    assert not shown.same_family_warning
    assert run.run_id in shown.record_html


def test_located_evidence_is_marked_and_nothing_else_is(tmp_path: Path) -> None:
    run = _question(tmp_path)
    report = run.report
    assert report is not None
    spans = [p.verdict.evidence_span for c in report.claims for p in c.pairs if p.outcome == "verdict"]
    shown = [p for p in _pairs(view(run)) if p.outcome == "verdict"]
    assert [p.highlighted for p in shown] == [s is not None for s in spans]
    assert any(p.highlighted for p in shown)
    for pair in shown:
        assert pair.abstract_html.count("<mark>") == int(pair.highlighted)


def test_a_citation_not_retrieved_shows_no_abstract_and_says_why(tmp_path: Path) -> None:
    missing = [p for p in _pairs(view(_question(tmp_path))) if p.outcome == "citation_not_retrieved"]
    assert missing
    for pair in missing:
        assert pair.failure == "citation_not_retrieved"
        assert pair.abstract_html == ""
        assert pair.title_html == ""
        assert pair.label is None


def test_a_verifier_failure_shows_the_abstract_unmarked_and_its_kind(tmp_path: Path) -> None:
    run = _question(tmp_path)
    report = run.report
    assert report is not None
    data = cast("dict[str, Any]", _strip(report.model_dump(mode="json")))
    pair = data["claims"][0]["pairs"][0]
    ids = {"claim_id": pair["verdict"]["claim_id"], "source_id": pair["verdict"]["source_id"]}
    data["claims"][0]["pairs"][0] = {"outcome": "failure", "failure": {**ids, "kind": "structured_output"}}
    shown = view_report(Report.model_validate(data), run)
    failed = shown.claims[0].pairs[0]
    assert failed.disposition == "failed"
    assert failed.failure == "structured_output"
    assert failed.abstract_html
    assert not failed.highlighted
    assert failed.reason_html is None


def test_a_check_shows_one_claim_against_its_paper(tmp_path: Path) -> None:
    run = _check(tmp_path)
    check = run.artifact
    assert isinstance(check, ClaimCheck)
    shown = view(run)
    assert shown.command == "check"
    assert shown.heading_html == check.claim.claim.text
    assert len(shown.claims) == 1
    (pair,) = shown.claims[0].pairs
    assert pair.source_id_html == check.paper.source_id
    assert pair.title_html == check.paper.title
    assert pair.label is not None
    assert shown.findings_html == ()


def _hostile_report(report: Report) -> Report:
    data = cast("dict[str, Any]", _strip(report.model_dump(mode="json")))
    data["question"] = HOSTILE
    for paper in data["papers"]:
        paper["title"] = HOSTILE
        paper["raw_abstract"] += " " + HOSTILE
    for claim in data["claims"]:
        claim["claim"]["text"] = HOSTILE
        for pair in claim["pairs"]:
            if pair["outcome"] == "verdict":
                pair["verdict"]["reason"] = HOSTILE
    return Report.model_validate(data)


def test_hostile_text_from_papers_users_and_models_is_escaped(tmp_path: Path) -> None:
    run = _question(tmp_path)
    report = run.report
    assert report is not None
    hostile = _hostile_report(report)
    assert HOSTILE in hostile.papers[0].abstract
    shown = view_report(hostile, run)
    assert all("<script>" not in t for t in _all_text(shown))
    assert "&lt;script&gt;" in shown.claims[0].text_html
    assert shown.heading_html == "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;q&quot; &#x27;a&#x27;"
    assert any(p.highlighted for p in _pairs(shown))
    for pair in _pairs(shown):
        assert "<" not in pair.abstract_html.replace("<mark>", "").replace("</mark>", "")


def test_a_hostile_check_is_escaped(tmp_path: Path) -> None:
    run = _check(tmp_path)
    check = run.artifact
    assert isinstance(check, ClaimCheck)
    data = cast("dict[str, Any]", _strip(check.model_dump(mode="json")))
    data["claim"]["claim"]["text"] = HOSTILE
    data["paper"]["title"] = HOSTILE
    data["claim"]["pairs"][0]["verdict"]["reason"] = HOSTILE
    shown = view_check(ClaimCheck.model_validate(data), run)
    assert all("<script>" not in t for t in _all_text(shown))
    assert "&lt;script&gt;" in shown.claims[0].pairs[0].title_html


ABSTRACT = CleanedText("Mice lost weight <b>fast</b>. OS-912 reduced weight in mice.")
QUOTE = "OS-912 reduced weight in mice"
PLAIN = "Mice lost weight &lt;b&gt;fast&lt;/b&gt;. OS-912 reduced weight in mice."


def test_highlight_marks_the_span_the_quote_locates() -> None:
    span = locate_quote(QUOTE, ABSTRACT)
    assert span == Span(30, 59)
    marked, highlighted = highlight(ABSTRACT, QUOTE, span)
    assert highlighted
    assert marked == "Mice lost weight &lt;b&gt;fast&lt;/b&gt;. <mark>OS-912 reduced weight in mice</mark>."


@pytest.mark.parametrize(
    ("quote", "span"),
    [
        (QUOTE, Span(0, 4)),  # a tampered span: the quote is elsewhere
        ("Mice lost weight", Span(30, 59)),  # a tampered quote: the span no longer holds it
        (QUOTE, Span(30, 999)),  # out of bounds
        (QUOTE, None),
        (None, Span(30, 59)),
        ("not in the abstract", Span(0, 4)),
    ],
)
def test_highlight_marks_nothing_unless_span_and_quote_agree(quote: str | None, span: Span | None) -> None:
    assert highlight(ABSTRACT, quote, span) == (PLAIN, False)


def test_clean_abstract_keeps_script_text_so_escaping_is_needed() -> None:
    assert "<script>" in clean_abstract("A finding. <script>x</script>")
