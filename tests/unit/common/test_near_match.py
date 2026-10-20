"""`near_match`: routing a near miss to needs-review. It never produces located evidence (ADR 0005)."""

import pytest

from bio_claim_check.common.text import (
    NEAR_MATCH_THRESHOLD,
    CleanedText,
    Span,
    _fold,  # pyright: ignore[reportPrivateUsage]
    _snap,  # pyright: ignore[reportPrivateUsage]
    _tokens,  # pyright: ignore[reportPrivateUsage]
    clean_abstract,
    locate_quote,
    near_match,
)

pytestmark = pytest.mark.unit

ABSTRACT = clean_abstract(
    "<h4>Background</h4>In this cohort, metformin treatment significantly reduced tumour growth in "
    "xenograft models compared with vehicle controls."
)


@pytest.mark.parametrize(
    "quote",
    [
        pytest.param(
            "metformin treatment significantly increased tumour growth in xenograft models", id="word-flip"
        ),
        pytest.param(
            "metformin treatment did not significantly reduce tumour growth in xenograft models", id="negated"
        ),
    ],
)
def test_meaning_flips_score_high_which_is_why_near_is_never_located(quote: str) -> None:
    assert locate_quote(quote, ABSTRACT) is None
    near = near_match(quote, ABSTRACT)
    assert near is not None
    assert near.score >= NEAR_MATCH_THRESHOLD
    assert near.span.of(ABSTRACT).startswith("metformin treatment significantly")


def test_case_only_difference_routes_to_review() -> None:
    near = near_match("Metformin treatment significantly reduced tumour growth", ABSTRACT)
    assert near is not None
    assert near.span.of(ABSTRACT) == "metformin treatment significantly reduced tumour growth"


@pytest.mark.parametrize(
    "quote",
    [
        pytest.param("statins improved cognition in elderly patients", id="unrelated"),
        pytest.param("reduced tumour", id="too-few-tokens"),
        pytest.param("", id="empty"),
    ],
)
def test_no_near_match(quote: str) -> None:
    assert near_match(quote, ABSTRACT) is None


def test_empty_text_has_no_near_match() -> None:
    assert near_match("metformin reduced tumour growth", CleanedText("")) is None


def test_span_lies_on_token_boundaries() -> None:
    near = near_match("formin treatment significantly increased tumour gro", ABSTRACT)
    assert near is not None
    starts = {t.start for t in _tokens(ABSTRACT)}
    ends = {t.end for t in _tokens(ABSTRACT)}
    assert near.span.start in starts
    assert near.span.end in ends


def test_repeated_phrase_returns_a_valid_region() -> None:
    phrase = "metformin treatment significantly reduced tumour growth in xenograft models"
    text = clean_abstract(f"{phrase}. Later, {phrase} again.")
    near = near_match(phrase.replace("reduced", "increased"), text)
    assert near is not None
    assert near.span.of(text) == phrase


def test_offsets_survive_characters_whose_lowercase_is_longer() -> None:
    text = clean_abstract("\u0130\u0130\u0130 metformin reduced tumour growth in mice")
    near = near_match("metformin increased tumour growth in mice", text)
    assert near is not None
    assert near.span.of(text) == "metformin reduced tumour growth in mice"


def test_fold_preserves_length() -> None:
    assert _fold("\u0130Ab") == "\u0130ab"


def test_snap_widens_to_whole_tokens_and_rejects_separator_only_regions() -> None:
    text = "ab cd"
    assert _snap(1, 4, _tokens(text)) == Span(0, 5)
    assert _snap(2, 3, _tokens(text)) is None


def test_deterministic() -> None:
    quote = "metformin treatment significantly increased tumour growth"
    assert near_match(quote, ABSTRACT) == near_match(quote, ABSTRACT)
