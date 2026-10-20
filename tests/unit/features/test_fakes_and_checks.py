"""Scripted answerer and verifier, the in-memory source and the invented-citation check (S05, S05b)."""

import pytest

from bio_claim_check.app.container import default_rulepack
from bio_claim_check.features.answer.scripted_answerer import SCRIPTS, ScriptedAnswerer
from bio_claim_check.features.checks.citations import invented_citations
from bio_claim_check.features.contracts.answer import Answer
from bio_claim_check.features.contracts.finding import FindingKind
from bio_claim_check.features.contracts.labels import AnswerMode, Disposition, EvidenceStatus
from bio_claim_check.features.contracts.verdict import Claim, Verdict
from bio_claim_check.features.retrieval.in_memory_literature_source import (
    FAKE_CORPUS,
    InMemoryLiteratureSource,
)
from bio_claim_check.features.verify.scripted_verifier import VERDICT_SCRIPT, ScriptedVerifier

pytestmark = pytest.mark.unit

RULES = default_rulepack()
BY_ID = {p.source_id: p for p in FAKE_CORPUS}


def test_fake_corpus_is_fictional_and_unique() -> None:
    ids = [p.source_id for p in FAKE_CORPUS]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith("FAKE:") for i in ids)


def test_fake_corpus_exercises_cleaning() -> None:
    raw = "".join(p.raw_abstract for p in FAKE_CORPUS)
    assert all(m in raw for m in ("<i>", "<sup>", "&lt;", "<h4>"))
    assert all("<" not in p.abstract.replace("p < ", "") for p in FAKE_CORPUS)


@pytest.mark.parametrize("limit", [1, 2, 4, 10])
def test_fake_source_respects_limit_in_rank_order(limit: int) -> None:
    assert InMemoryLiteratureSource().search("anything", limit=limit) == FAKE_CORPUS[:limit]


@pytest.mark.parametrize("mode", list(AnswerMode))
def test_scripted_answer_echoes_question_and_mode(mode: AnswerMode) -> None:
    answer = ScriptedAnswerer().answer("Does OS-912 work?", FAKE_CORPUS, mode)
    assert (answer.question, answer.mode, answer.claims) == ("Does OS-912 work?", mode, SCRIPTS[mode])


EXPECTED = {
    ("s1", "FAKE:1"): (Disposition.NEEDS_REVIEW, EvidenceStatus.LOCATED),
    ("s2", "FAKE:3"): (Disposition.NEEDS_REVIEW, EvidenceStatus.LOCATED),
    ("s2", "FAKE:4"): (Disposition.FLAGGED, EvidenceStatus.NOT_REQUIRED),
    ("s3", "FAKE:2"): (Disposition.NEEDS_REVIEW, EvidenceStatus.LOCATED),
    ("o1", "FAKE:1"): (Disposition.FLAGGED, EvidenceStatus.LOCATED),
    ("o2", "FAKE:3"): (Disposition.FLAGGED, EvidenceStatus.LOCATED),
    ("o3", "FAKE:2"): (Disposition.FLAGGED, EvidenceStatus.ABSENT),
    ("o4", "FAKE:1"): (Disposition.NEEDS_REVIEW, EvidenceStatus.NEAR),
}


def test_every_scripted_pair_is_covered_by_the_expectations() -> None:
    assert set(VERDICT_SCRIPT) == {*EXPECTED, ("o6", "FAKE:4")}


@pytest.mark.parametrize(("pair", "expected"), list(EXPECTED.items()), ids=str)
def test_scripted_verdicts_get_their_evidence_status_from_code(
    pair: tuple[str, str], expected: tuple[Disposition, EvidenceStatus]
) -> None:
    claim_id, source_id = pair
    claim = next(c for script in SCRIPTS.values() for c in script if c.id == claim_id)
    verdict = ScriptedVerifier().verify(claim, BY_ID[source_id], RULES)
    assert isinstance(verdict, Verdict)
    assert (verdict.disposition, verdict.evidence_status) == expected
    verdict.verify_against(BY_ID[source_id].abstract)


def test_scripted_failure_is_a_counted_failure() -> None:
    claim = Claim(id="o6", text="x", cites=("FAKE:4",))
    assert ScriptedVerifier().verify(claim, BY_ID["FAKE:4"], RULES).disposition is Disposition.FAILED


def test_unscripted_pair_is_a_test_bug_not_a_verdict() -> None:
    with pytest.raises(KeyError, match="no scripted verdict"):
        ScriptedVerifier().verify(Claim(id="zz", text="x", cites=("FAKE:1",)), BY_ID["FAKE:1"], RULES)


def test_invented_citations_one_per_pair_in_order() -> None:
    claims = (
        Claim(id="a", text="x", cites=("FAKE:9", "FAKE:1", "FAKE:8")),
        Claim(id="b", text="y", cites=("FAKE:9",)),
    )
    answer = Answer(question="q", mode=AnswerMode.STRICT, claims=claims)
    found = invented_citations(answer, {"FAKE:1"})
    assert [(f.claim_id, f.source_id) for f in found] == [("a", "FAKE:9"), ("a", "FAKE:8"), ("b", "FAKE:9")]
    assert {f.kind for f in found} == {FindingKind.INVENTED_CITATION}


def test_no_findings_when_every_cite_was_retrieved() -> None:
    answer = Answer(question="q", mode=AnswerMode.STRICT, claims=SCRIPTS[AnswerMode.STRICT])
    assert invented_citations(answer, BY_ID.keys()) == ()
