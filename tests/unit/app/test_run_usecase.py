"""`run_question`: the use case distrusts every port (I18)."""

from dataclasses import replace
from typing import override

import pytest

from bio_claim_check.app.container import build_fake_run_ports
from bio_claim_check.app.usecases.run import RunPorts, run_question
from bio_claim_check.features.answer.base_answerer import BaseAnswerer
from bio_claim_check.features.answer.scripted_answerer import ScriptedAnswerer
from bio_claim_check.features.contracts.answer import Answer
from bio_claim_check.features.contracts.labels import AnswerMode, Disposition, EvidenceStatus, Label
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.rulepack import RulePack
from bio_claim_check.features.contracts.verdict import (
    CitationNotRetrieved,
    Claim,
    Verdict,
    VerifierFailure,
    VerifierOutput,
)
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.retrieval.in_memory_literature_source import (
    FAKE_CORPUS,
    InMemoryLiteratureSource,
)
from bio_claim_check.features.verify.base_verifier import BaseVerifier
from bio_claim_check.features.verify.scripted_verifier import ScriptedVerifier

pytestmark = pytest.mark.unit

Q = "Does OS-912 slow cognitive decline?"


class SpyVerifier(BaseVerifier):
    """Records every call and delegates to the scripted verifier."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._inner = ScriptedVerifier()

    @override
    def verify(self, claim: Claim, paper: Paper, rules: RulePack) -> Verdict | VerifierFailure:
        self.calls.append((claim.id, paper.source_id))
        return self._inner.verify(claim, paper, rules)


class FixedAnswerer(BaseAnswerer):
    def __init__(
        self, claims: tuple[Claim, ...], question: str | None = None, mode: AnswerMode | None = None
    ):
        self._claims, self._question, self._mode = claims, question, mode

    @override
    def answer(self, question: str, papers: tuple[Paper, ...], mode: AnswerMode) -> Answer:
        return Answer(question=self._question or question, mode=self._mode or mode, claims=self._claims)


class FixedSource(BaseLiteratureSource):
    def __init__(self, papers: tuple[Paper, ...]) -> None:
        self._papers = papers

    @override
    def search(self, question: str, *, limit: int) -> tuple[Paper, ...]:
        return self._papers


def _container(**changes: object) -> RunPorts:
    return replace(build_fake_run_ports(), **changes)


@pytest.mark.parametrize("k", [0, -1, True, 2.0])
def test_k_must_be_a_positive_int(k: object) -> None:
    with pytest.raises(ValueError, match="k must be"):
        run_question(build_fake_run_ports(), Q, AnswerMode.STRICT, k=k)  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("question", ["", "   ", "\t\n"])
def test_question_must_not_be_blank(question: str) -> None:
    with pytest.raises(ValueError, match="blank"):
        run_question(build_fake_run_ports(), question, AnswerMode.STRICT, k=4)


def test_source_returning_more_than_k_is_rejected() -> None:
    with pytest.raises(ValueError, match="returned 4 papers for limit=2"):
        run_question(_container(literature=FixedSource(FAKE_CORPUS)), Q, AnswerMode.STRICT, k=2)


def test_source_returning_duplicates_is_rejected() -> None:
    source = FixedSource((FAKE_CORPUS[0], FAKE_CORPUS[0]))
    with pytest.raises(ValueError, match="duplicate"):
        run_question(_container(literature=source), Q, AnswerMode.STRICT, k=4)


@pytest.mark.parametrize(("question", "mode"), [("Another question?", None), (None, AnswerMode.OVER_EAGER)])
def test_answer_must_echo_question_and_mode(question: str | None, mode: AnswerMode | None) -> None:
    answerer = FixedAnswerer((), question=question, mode=mode)
    with pytest.raises(ValueError, match="different question or mode"):
        run_question(_container(answerer=answerer), Q, AnswerMode.STRICT, k=4)


def test_non_retrieved_cites_never_reach_the_verifier() -> None:
    spy = SpyVerifier()
    report = run_question(_container(verifier=spy), Q, AnswerMode.OVER_EAGER, k=4)
    assert ("o5", "FAKE:99") not in spy.calls
    pair = next(p for c in report.claims for p in c.pairs if p.result.source_id == "FAKE:99")
    assert isinstance(pair.result, CitationNotRetrieved)
    assert pair.disposition is Disposition.FLAGGED
    assert [(f.claim_id, f.source_id) for f in report.findings] == [("o5", "FAKE:99")]


def test_verifier_receives_exactly_the_cited_paper() -> None:
    spy = SpyVerifier()
    run_question(_container(verifier=spy), Q, AnswerMode.STRICT, k=4)
    assert spy.calls == [("s1", "FAKE:1"), ("s2", "FAKE:3"), ("s2", "FAKE:4"), ("s3", "FAKE:2")]


def test_empty_retrieval_makes_every_cite_not_retrieved() -> None:
    spy = SpyVerifier()
    report = run_question(_container(verifier=spy, literature=FixedSource(())), Q, AnswerMode.STRICT, k=4)
    assert spy.calls == []
    assert report.pair_counts[Disposition.FLAGGED] == sum(len(c.claim.cites) for c in report.claims) == 4
    assert len(report.findings) == 4


def test_small_k_reports_unretrieved_cites_honestly() -> None:
    report = run_question(build_fake_run_ports(), Q, AnswerMode.STRICT, k=1)
    assert [p.source_id for p in report.papers] == ["FAKE:1"]
    assert {(f.claim_id, f.source_id) for f in report.findings} == {
        ("s2", "FAKE:3"),
        ("s2", "FAKE:4"),
        ("s3", "FAKE:2"),
    }


def test_same_source_cited_by_two_claims_is_verified_twice() -> None:
    claims = (
        Claim(id="s1", text="a", cites=("FAKE:1", "FAKE:99")),
        Claim(id="o4", text="b", cites=("FAKE:1", "FAKE:99")),
    )
    spy = SpyVerifier()
    report = run_question(_container(verifier=spy, answerer=FixedAnswerer(claims)), Q, AnswerMode.STRICT, k=4)
    assert spy.calls == [("s1", "FAKE:1"), ("o4", "FAKE:1")]
    assert [(f.claim_id, f.source_id) for f in report.findings] == [("s1", "FAKE:99"), ("o4", "FAKE:99")]


def test_zero_claims_gives_an_empty_report() -> None:
    report = run_question(_container(answerer=FixedAnswerer(())), Q, AnswerMode.STRICT, k=4)
    assert report.claims == ()
    assert report.findings == ()
    assert set(report.pair_counts.values()) == {0}


class ForgingVerifier(BaseVerifier):
    """Returns an internally consistent verdict whose span was located in a different abstract."""

    @override
    def verify(self, claim: Claim, paper: Paper, rules: RulePack) -> Verdict | VerifierFailure:
        out = VerifierOutput(
            label=Label.SUPPORTED, overstated_reason=None, evidence="OS-912 use was associated", reason="r"
        )
        return Verdict.finalise(claim.id, paper.source_id, out, FAKE_CORPUS[2].abstract)


def test_a_forged_span_from_another_abstract_is_rejected() -> None:
    forged = ForgingVerifier().verify(
        ScriptedAnswerer().answer(Q, (), AnswerMode.STRICT).claims[0],
        FAKE_CORPUS[0],
        build_fake_run_ports().rules,
    )
    assert isinstance(forged, Verdict)
    assert forged.evidence_status is EvidenceStatus.LOCATED
    with pytest.raises(ValueError, match="does not match the abstract"):
        run_question(_container(verifier=ForgingVerifier()), Q, AnswerMode.STRICT, k=4)


def test_fake_source_ignores_question_text() -> None:
    assert InMemoryLiteratureSource().search("x", limit=4) == InMemoryLiteratureSource().search(Q, limit=4)
