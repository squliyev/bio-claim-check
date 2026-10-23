"""`dangling_claims`: narrow on purpose, so a flag means the claim really points outside itself (P2)."""

import pytest

from bio_claim_check.features.checks.self_containment import dangling_claims
from bio_claim_check.features.contracts.answer import Answer
from bio_claim_check.features.contracts.finding import FindingKind
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.contracts.verdict import Claim

pytestmark = pytest.mark.unit


def _answer(*texts: str) -> Answer:
    claims = tuple(Claim(id=f"c{i}", text=t, cites=("FAKE:1",)) for i, t in enumerate(texts, 1))
    return Answer(question="Does OS-912 work?", mode=AnswerMode.OVER_EAGER, claims=claims)


@pytest.mark.parametrize(
    ("text", "phrase"),
    [
        ("This drug slowed cognitive decline.", "This"),
        ("These findings suggest a benefit in patients.", "These"),
        ("Such effects were seen in mice.", "Such"),
        ("It reduced plaque load by 38%.", "It"),
        ("They had fewer dementia diagnoses.", "They"),
        ('"This compound" lowered plaque.', "This"),
        ("OS-912 had the same effect as the aforementioned compound.", "the aforementioned"),
        ("The authors report a 38% reduction.", "The authors"),
        ("As noted above, OS-912 lowered plaque.", "noted above"),
        ("OS-912, as shown earlier, lowered plaque.", "as shown earlier"),
        ("OS-912 extends the previous claim to humans.", "previous claim"),
        ("The latter lowered plaque in mice.", "The latter"),
    ],
)
def test_a_reference_outside_the_claim_is_flagged(text: str, phrase: str) -> None:
    (finding,) = dangling_claims(_answer(text))
    assert (finding.kind, finding.claim_id, finding.source_id) == (FindingKind.DANGLING_REFERENCE, "c1", None)
    assert phrase.lower() in finding.detail.lower()


@pytest.mark.parametrize(
    "text",
    [
        "OS-912 reduced amyloid plaque load in APP/PS1 mice.",
        "OS-912 lowered plaque, and this effect lasted 12 weeks.",
        "Thiazolidinediones lowered glucose.",
        "Itraconazole had no effect on plaque.",
        "Theyer scores improved.",
        "In mice, OS-912 reduced plaque; it did not change memory.",
    ],
)
def test_a_self_contained_claim_is_not_flagged(text: str) -> None:
    assert dangling_claims(_answer(text)) == ()


def test_findings_follow_claim_order_and_an_abstention_has_none() -> None:
    answer = _answer("OS-912 lowered plaque.", "These results hold.", "This drug works.")
    assert [f.claim_id for f in dangling_claims(answer)] == ["c2", "c3"]
    assert dangling_claims(Answer(question="q", mode=AnswerMode.STRICT, claims=())) == ()
