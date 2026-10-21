"""Sieve v1 (ADR 0010): one accepting and one rejecting row per rule and exclusion."""

import pytest
from tests.support.papers import paper

from bio_claim_check.common.text import CleanedText
from bio_claim_check.features.contracts.corpus import TRAP_KINDS, NeverReason
from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.corpus.eligibility import candidates, exclusions, sentences

PRE = OverstatedReason.PRECLINICAL_TO_CLINICAL
OBS = OverstatedReason.CORRELATION_AS_CAUSATION
NULL = OverstatedReason.NONSIGNIFICANT_AS_EFFECT
HEDGE = OverstatedReason.CERTAINTY_INFLATION


def kinds_of(p: Paper) -> dict[OverstatedReason, str]:
    return {c.kind: c.rule for c in candidates(p, TRAP_KINDS)}


def test_plain_human_article_is_no_candidate() -> None:
    assert kinds_of(paper()) == {}


@pytest.mark.parametrize(
    ("mesh", "types", "rule"),
    [
        (("Animals", "Mice"), ("Journal Article",), "animals_not_humans"),
        (("Humans", "Cell Line, Tumor"), ("Journal Article",), "in_vitro"),
        (("Cells, Cultured",), ("Journal Article",), "in_vitro"),
    ],
)
def test_preclinical_accepts(mesh: tuple[str, ...], types: tuple[str, ...], rule: str) -> None:
    assert kinds_of(paper(mesh=mesh, types=types))[PRE] == rule


@pytest.mark.parametrize(
    ("mesh", "types"),
    [
        (("Animals", "Humans"), ("Journal Article",)),  # animals together with humans
        (("Humans", "Cell Line", "Cohort Studies"), ("Journal Article",)),  # clinical design MeSH
        (("Humans", "Cell Line"), ("Randomized Controlled Trial",)),
        (("Humans", "Cell Line"), ("Clinical Trial, Phase II",)),
        (("Humans", "Cell Line"), ("Observational Study",)),
        (("Humans", "Cell Line", "Prospective Studies"), ("Journal Article",)),
        (("Humans", "Cell Line", "Retrospective Studies"), ("Journal Article",)),
        (("Humans", "Cell Line", "Cross-Sectional Studies"), ("Journal Article",)),
        (("Humans", "Cell Line", "Clinical Trials as Topic"), ("Journal Article",)),
    ],
)
def test_preclinical_rejects(mesh: tuple[str, ...], types: tuple[str, ...]) -> None:
    assert PRE not in kinds_of(paper(mesh=mesh, types=types))


def test_observational_by_mesh_or_type() -> None:
    found = candidates(paper(mesh=("Humans", "Cohort Studies")), (OBS,))
    assert [(c.rule, c.mesh, c.publication_types) for c in found] == [
        ("observational", ("Cohort Studies",), ())
    ]
    found = candidates(paper(types=("Journal Article", "Observational Study")), (OBS,))
    assert found[0].publication_types == ("Observational Study",)


def test_rct_with_cohort_mesh_is_not_correlation() -> None:
    rct = paper(mesh=("Humans", "Cohort Studies"), types=("Randomized Controlled Trial",))
    assert OBS not in kinds_of(rct)


@pytest.mark.parametrize(
    ("sentence", "hit"),
    [
        ("The difference was not significant.", True),
        ("There was no statistically significant change.", True),
        ("Groups were not significantly different.", True),
        ("There was no significance testing.", False),
        ("Treatment did not improve survival.", True),
        ("The effect was small (p = 0.05).", True),
        ("The effect was small (p = .06).", True),
        ("The effect was small (p ≥ 0.1).", True),
        ("The effect was small (p > 0.05).", True),
        ("The effect was small (p = 0.9).", True),
        ("The effect was small (p = 0.95).", True),
        ("The effect was small, p = 0.05.", True),
        ("The effect was clear (p = 0.0499).", False),
        ("The effect was clear (p = 0.049).", False),
        ("The effect was clear (p < 0.05).", False),
        ("The effect was clear (p = 0.001).", False),
    ],
)
def test_null_result(sentence: str, hit: bool) -> None:
    abstract = f"Patients were enrolled. {sentence} Results are reported."
    found = candidates(paper(abstract=abstract), (NULL,))
    assert bool(found) is hit
    if hit:
        span = found[0].span
        assert span is not None
        assert span.of(paper(abstract=abstract).abstract) == sentence


def test_hedge_only_counts_in_the_last_two_sentences() -> None:
    early = "This may matter. We enrolled patients. Outcomes were measured. Survival improved."
    late = "We enrolled patients. Outcomes were measured. Survival improved. It may help others."
    assert candidates(paper(abstract=early), (HEDGE,)) == ()
    found = candidates(paper(abstract=late), (HEDGE,))
    assert found[0].span is not None
    assert found[0].span.of(paper(abstract=late).abstract) == "It may help others."


@pytest.mark.parametrize(
    "text",
    [
        "Drugs, e.g. Metformin were used.",
        "As in Smith et al. Results were similar.",
        "Arm A vs. Arm B was tested.",
        "See Fig. 2 for details.",
        "The dose was 2.5 mg daily.",
    ],
)
def test_abbreviations_and_decimals_do_not_split(text: str) -> None:
    assert len(sentences(CleanedText(text))) == 1


def test_sentence_spans() -> None:
    text = CleanedText("One. Two! (Three) four? 5 is last.")
    assert [s.of(text) for s in sentences(text)] == ["One.", "Two!", "(Three) four?", "5 is last."]
    assert sentences(CleanedText("")) == ()


def test_empty_abstract_has_no_text_candidates() -> None:
    assert candidates(paper(abstract=""), (NULL, HEDGE)) == ()


@pytest.mark.parametrize(
    ("p", "reasons"),
    [
        (paper(retracted=True), (NeverReason.RETRACTED,)),
        (paper(types=("Review",)), (NeverReason.REVIEW,)),
        (paper(types=("Journal Article", "Meta-Analysis")), (NeverReason.REVIEW,)),
        (paper(types=()), (NeverReason.UNKNOWN_PUBLICATION_TYPES,)),
        (paper(mesh=None), (NeverReason.MESH_NOT_INDEXED,)),
        (
            paper(retracted=True, mesh=None, types=()),
            (NeverReason.RETRACTED, NeverReason.UNKNOWN_PUBLICATION_TYPES, NeverReason.MESH_NOT_INDEXED),
        ),
    ],
)
def test_exclusions(p: Paper, reasons: tuple[NeverReason, ...]) -> None:
    assert exclusions(p) == reasons


_HITS = "No significant change was seen (p = 0.3). These results may help."


@pytest.mark.parametrize(
    "p",
    [
        paper(mesh=("Animals",), abstract=_HITS, retracted=True),
        paper(mesh=("Animals",), abstract=_HITS, types=("Review",)),
        paper(mesh=("Animals",), abstract=_HITS, types=()),
    ],
)
def test_excluded_papers_are_never_candidates(p: Paper) -> None:
    assert exclusions(p)
    assert candidates(p, TRAP_KINDS) == ()


def test_unindexed_mesh_blocks_only_mesh_kinds() -> None:
    found = candidates(paper(mesh=None, abstract=_HITS, types=("Observational Study",)), TRAP_KINDS)
    assert [c.kind for c in found] == [NULL, HEDGE]


def test_candidates_follow_kinds_order_and_reject_unknown_kinds() -> None:
    p = paper(mesh=("Animals",), abstract="Nothing changed. Effects were not significant.")
    assert [c.kind for c in candidates(p, (NULL, PRE))] == [NULL, PRE]
    with pytest.raises(ValueError, match="surrogate_as_clinical"):
        candidates(p, (OverstatedReason.SURROGATE_AS_CLINICAL,))
