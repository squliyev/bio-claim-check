"""`locate_quote` and `Span`: the behaviour table (rules L1-L31) from ADR 0005.

Each row is one rule a reviewer can read. "None" rows are false-located risks that must fail closed.
"""

import pytest

from bio_claim_check.common.text import CleanedText, Span, clean_abstract, locate_quote

pytestmark = pytest.mark.unit

LOCATED = True
NONE = False


@pytest.mark.parametrize(
    ("quote", "raw_text", "located"),
    [
        pytest.param(
            "metformin reduced tumour-growth",
            "In mice metformin reduced tumour-growth.",
            LOCATED,
            id="L1-verbatim",
        ),
        pytest.param("Reduced tumour", "it reduced tumour size", NONE, id="L1b-sentence-case"),
        pytest.param("akt signalling", "AKT signalling", NONE, id="L1b-gene-case"),
        pytest.param("5 ms", "5 MS", NONE, id="L1b-ms-vs-MS"),
        pytest.param("2 mg dose", "2 Mg dose", NONE, id="L1b-mg-vs-Mg"),
        pytest.param("reduced, tumour growth", "reduced tumour growth", LOCATED, id="L2-punctuation-ignored"),
        pytest.param("increased tumour growth", "metformin reduced tumour growth", NONE, id="L3-word-flip"),
        pytest.param("p > 0.05", "was significant (p < 0.05).", NONE, id="L4-operator-flip"),
        pytest.param("p = 0.05", "p <= 0.05", NONE, id="L5-multichar-operator"),
        pytest.param("creased tumour", "increased tumour", NONE, id="L6-partial-word"),
        pytest.param("1.5 mg", "15 mg", NONE, id="L7-decimal-vs-integer"),
        pytest.param("0.05", "p = 0.005", NONE, id="L8-decimal-inside-decimal"),
        pytest.param("by 0.5", "fell by -0.5", NONE, id="L9-sign"),
        pytest.param("10^5 cells", "10<sup>5</sup> cells", LOCATED, id="L10-exponent-kept"),
        pytest.param("105 cells", "10<sup>5</sup> cells", NONE, id="L11-exponent-not-glued"),
        pytest.param("GLP 1 receptor", "GLP-1 receptor", NONE, id="L12-identifier-hyphen"),
        pytest.param("IC50", "an IC<sub>50</sub> of", LOCATED, id="L13-sub-inline"),
        pytest.param("\u00b5M", "10 \u03bcM", LOCATED, id="L14-micro-vs-mu"),
        pytest.param("", "anything", NONE, id="L16-empty"),
        pytest.param("...", "anything...", NONE, id="L16-no-tokens"),
        pytest.param("p<0.05", "p < 0.05", LOCATED, id="L17-operator-needs-no-space"),
        pytest.param(
            "significant reduction", "no significant reduction", LOCATED, id="L18-negation-known-limit"
        ),
        pytest.param("Na+ influx", "Na influx", NONE, id="L19-sodium-charge"),
        pytest.param("NAD+ levels", "NAD levels", NONE, id="L19-nad-charge"),
        pytest.param("K+ channel", "K- channel", NONE, id="L19-charge-flip"),
        pytest.param("Na/K ratio", "Na K ratio", NONE, id="L20-slash"),
        pytest.param("1e-5", "IC50 1e-6", NONE, id="L21-scientific-exponent"),
        pytest.param("1\u00d710^-5", "1\u00d710<sup>-6</sup>", NONE, id="L21-sup-exponent"),
        pytest.param("1-5 mg", "1\u20135 mg", LOCATED, id="L22-en-dash-range"),
        pytest.param("IL 6", "IL-6 rose", NONE, id="L23-il6"),
        pytest.param("BCR ABL1", "BCR-ABL1", NONE, id="L23-fusion"),
        pytest.param("reduced growth", "reduced\u2014growth", LOCATED, id="L24-em-dash"),
        pytest.param("\u221212.5%", "fell -12.5 %", LOCATED, id="L25-minus-percent"),
        pytest.param("\u03b22 agonist", "beta2 agonist", NONE, id="L26-no-transliteration"),
        pytest.param("95% CI 1.2, 1.5", "95% CI [1.2, 1.5]", LOCATED, id="L27-brackets-are-notation"),
        pytest.param("drug response", "drug\u200bresponse", LOCATED, id="L28-zwsp"),
        pytest.param("1,000 patients", "1.000 patients", NONE, id="L29-separator-dot"),
        pytest.param("1,000 patients", "1000 patients", NONE, id="L29-separator-none"),
        pytest.param("p = .05", "p = .05", LOCATED, id="leading-decimal"),
        pytest.param("p = .05", "p = 0.05", NONE, id="leading-decimal-vs-zero"),
        pytest.param("~50%", "\u223c50%", LOCATED, id="tilde-operator"),
        pytest.param("~50%", "50%", NONE, id="approx-is-evidence"),
        pytest.param("\u224850%", "~50%", NONE, id="approx-vs-tilde"),
        pytest.param("quote longer than the text", "short", NONE, id="quote-longer-than-text"),
        pytest.param("5 mg", "dose 5 mg/kg daily", NONE, id="L30-unit-continues"),
        pytest.param("ER+", "ER+/- tumours", NONE, id="L30-genotype-continues"),
        pytest.param("HER2", "HER2- disease", NONE, id="L30-trailing-sign"),
        pytest.param("5 cells", "10<sup>5</sup> cells", NONE, id="L30-exponent-precedes"),
        pytest.param("1 receptor", "GLP-1 receptor", NONE, id="L30-identifier-precedes"),
        pytest.param("Ink4a mice", "Ink4a<sup>-/-</sup> mice", NONE, id="L30-genotype-dropped"),
        pytest.param("p < 0.05", "significant (p < 0.05).", LOCATED, id="L30-brackets-do-not-touch"),
        pytest.param("10 C", "at 10 °C", NONE, id="L31-degree-is-evidence"),
        pytest.param("R D", "R&D spend", NONE, id="L31-ampersand-is-evidence"),
        pytest.param("10 °C", "at 10 °C", LOCATED, id="L31-symbol-verbatim"),
        pytest.param("105 cells", "10<jats:sup>5</jats:sup> cells", NONE, id="L11-namespaced-sup"),
    ],
)
def test_behaviour_table(quote: str, raw_text: str, located: bool) -> None:
    assert (locate_quote(quote, clean_abstract(raw_text)) is not None) is located


def test_span_covers_first_to_last_matched_token() -> None:
    text = clean_abstract("In mice, metformin reduced (tumour) growth.")
    span = locate_quote("metformin reduced tumour growth", text)
    assert span is not None
    assert span.of(text) == "metformin reduced (tumour) growth"


def test_l15_first_occurrence_wins() -> None:
    text = clean_abstract("reduced A. Later it reduced B.")
    assert locate_quote("reduced", text) == Span(0, 7)


def test_signed_number_span_includes_the_sign() -> None:
    text = clean_abstract("change of -0.5 units")
    span = locate_quote("-0.5", text)
    assert span is not None
    assert span.of(text) == "-0.5"


def test_quote_is_normalised_like_the_text() -> None:
    text = clean_abstract("10<sup>\u22126</sup> M")
    assert locate_quote("10\u207b\u2076 M", text) is not None  # Unicode superscripts in the quote


@pytest.mark.parametrize(("start", "end"), [(-1, 2), (3, 3), (4, 2)])
def test_span_rejects_invalid_bounds(start: int, end: int) -> None:
    with pytest.raises(ValueError, match="invalid span"):
        Span(start, end)


def test_span_of_rejects_text_that_is_too_short() -> None:
    with pytest.raises(ValueError, match="exceeds text length"):
        Span(0, 5).of(CleanedText("abc"))


@pytest.mark.parametrize(("start", "end"), [(True, 2), (0, 2.0), ("1", 2)])
def test_span_rejects_non_int_offsets(start: object, end: object) -> None:
    with pytest.raises(TypeError, match="must be int"):
        Span(start, end)  # pyright: ignore[reportArgumentType] -- wrong type on purpose
