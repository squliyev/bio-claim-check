"""The negation detector is conservative: a false CLEAR (a wrong PASSED) is the case tested hardest."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from bio_claim_check.common.negation import is_negated, sentence_bounds
from bio_claim_check.common.text import CleanedText, Span, clean_abstract, locate_quote

pytestmark = pytest.mark.unit


def _negated(abstract: str, quote: str) -> bool:
    text = clean_abstract(abstract)
    span = locate_quote(quote, text)
    assert span is not None, "test quote must locate"
    return is_negated(span, text)


@pytest.mark.parametrize(
    ("abstract", "quote"),
    [
        pytest.param("There was no significant reduction in plaque load.", "significant reduction", id="L18"),
        pytest.param(
            "Exenatide did not improve motor scores at 48 weeks.", "improve motor scores", id="did-not"
        ),
        pytest.param("Exenatide didn't improve motor scores.", "improve motor scores", id="contraction"),
        pytest.param(
            "Exenatide didn\u2019t improve motor scores.", "improve motor scores", id="curly-apostrophe"
        ),
        pytest.param(
            "There was no statistically significant difference between arms in the mean change of "
            "the total motor score at week 48.",
            "the total motor score at week 48",
            id="cue-far-before",
        ),
        pytest.param(
            "Drug X improved survival was not observed.", "Drug X improved survival", id="cue-after"
        ),
        pytest.param("Drug X did not improve survival.", "Drug X did not improve survival", id="cue-inside"),
        pytest.param(
            "The trial failed to show a benefit on survival.", "a benefit on survival", id="failed-to"
        ),
        pytest.param("We saw an absence of effect on HbA1c.", "effect on HbA1c", id="absence-of"),
        pytest.param("The change was non-significant in women.", "in women", id="non-significant"),
        pytest.param("The change was nonsignificantly lower.", "lower", id="nonsignificantly"),
        pytest.param("Neither dose altered weight.", "altered weight", id="neither"),
        pytest.param("Patients without diabetes had fewer events.", "had fewer events", id="without"),
        pytest.param("Metformin lacked an effect on growth.", "an effect on growth", id="lacked"),
        pytest.param("None of the mice responded.", "the mice responded", id="none"),
        pytest.param(
            "Results: No benefit; survival improved in mice.", "survival improved in mice", id="semicolon"
        ),
        pytest.param(
            "Cells were treated (vs. no drug) and grew.", "and grew", id="abbreviation-before-lower"
        ),
    ],
)
def test_any_cue_in_the_sentence_is_negated(abstract: str, quote: str) -> None:
    assert _negated(abstract, quote)


@pytest.mark.parametrize(
    ("abstract", "quote"),
    [
        pytest.param("Metformin reduced tumour growth in mice.", "reduced tumour growth", id="plain"),
        pytest.param(
            "There was no change in weight. Metformin reduced tumour growth in mice.",
            "reduced tumour growth",
            id="cue-in-previous-sentence",
        ),
        pytest.param(
            "Metformin reduced tumour growth in mice. It did not change weight.",
            "reduced tumour growth",
            id="cue-in-next-sentence",
        ),
        pytest.param(
            "Exenatide not only improved motor scores but also mood.", "improved motor scores", id="not-only"
        ),
        pytest.param(
            "Notably, knockout mice gained weight.", "knockout mice gained weight", id="no-inside-words"
        ),
        pytest.param("The nominal dose reduced glucose.", "reduced glucose", id="nominal"),
    ],
)
def test_no_cue_in_the_sentence_is_clear(abstract: str, quote: str) -> None:
    assert not _negated(abstract, quote)


def test_a_span_across_sentences_reads_both() -> None:
    text = clean_abstract("Weight fell. Glucose did not change. Insulin rose.")
    span = locate_quote("Weight fell. Glucose", text)
    assert span is not None
    assert sentence_bounds(span, text) == (0, len("Weight fell. Glucose did not change."))
    assert is_negated(span, text)


@pytest.mark.parametrize(
    "abstract",
    [
        pytest.param("No effect was seen in Fig. S1 for OS-912 recipients.", id="fig"),
        pytest.param("No gain was reported by Smith et al. For OS-912 recipients.", id="et-al"),
        pytest.param("No gain vs. Placebo arms in OS-912 recipients.", id="vs"),
        pytest.param("No gain (cf. Table 2) in OS-912 recipients.", id="cf"),
    ],
)
def test_an_abbreviation_does_not_end_the_sentence(abstract: str) -> None:
    assert _negated(abstract, "OS-912 recipients")


def test_a_span_ending_on_the_full_stop_keeps_its_sentence() -> None:
    text = CleanedText("Weight fell. Glucose did not change.")
    assert sentence_bounds(Span(0, 12), text) == (0, 12)


def test_a_span_outside_the_text_raises() -> None:
    with pytest.raises(ValueError, match="exceeds text length"):
        is_negated(Span(0, 50), CleanedText("short"))


@given(st.text(min_size=1, max_size=200), st.data())
def test_a_trailing_cue_always_negates(prefix: str, data: st.DataObject) -> None:
    """A cue right after any span in its sentence always negates it, whatever came before."""
    body = CleanedText(f"{prefix.replace('.', ' ')} weight fell")
    start = data.draw(st.integers(0, len(body) - 1))
    span = Span(start, len(body))
    assert is_negated(span, CleanedText(f"{body} not"))
