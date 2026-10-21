"""Property tests for `common.text` with an oracle that never calls the tokenizer.

Texts and quotes are generated as lists of ITEMS. Each item records, by hand, the tokens it must
produce. The oracle is a plain contiguous-subsequence search over those hand-written token lists. If
the tokenizer ever splits or merges differently from the hand-written list, the properties fail.
"""

import unicodedata

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

# the properties pin the private tokeniser
from bio_claim_check.common.text import CleanedText, _tokens, clean_abstract, locate_quote  # pyright: ignore[reportPrivateUsage]

pytestmark = pytest.mark.unit

# item text -> the tokens it must produce (written by hand; the oracle's only source of truth)
ITEMS: dict[str, tuple[str, ...]] = {
    "metformin": ("metformin",),
    "reduced": ("reduced",),
    "Reduced": ("Reduced",),
    "increased": ("increased",),
    "tumour": ("tumour",),
    "p": ("p",),
    "mg": ("mg",),
    "Mg": ("Mg",),
    "β2": ("β2",),
    "beta2": ("beta2",),
    "IC50": ("IC50",),
    "Na": ("Na",),
    "0.05": ("0.05",),
    "0.005": ("0.005",),
    "1.5": ("1.5",),
    "15": ("15",),
    "-0.5": ("-0.5",),
    "0.5": ("0.5",),
    "+2": ("+2",),
    "1,000": ("1,000",),
    "1.000": ("1.000",),
    "1000": ("1000",),
    "1e-5": ("1e-5",),
    "1e-6": ("1e-6",),
    "1e5": ("1e5",),
    ".05": (".05",),
    "<": ("<",),
    "<=": ("<=",),
    ">": (">",),
    ">=": (">=",),
    "=": ("=",),
    "!=": ("!=",),
    "±": ("±",),
    "%": ("%",),
    "≥": ("≥",),
    "≤": ("≤",),
    "\u00d7": ("\u00d7",),
    "~": ("~",),
    "≈": ("≈",),
    "/": ("/",),
    "+": ("+",),
    "-": ("-",),
    "GLP-1": ("GLP", "-", "1"),
    "IL-6": ("IL", "-", "6"),
    "Na+": ("Na", "+"),
    "Na/K": ("Na", "/", "K"),
    "10^-6": ("10", "^", "-6"),
    "10^5": ("10", "^", "5"),
    "x2": ("x2",),
    "10 °C": ("10", "°", "C"),
    "C": ("C",),
    "R&D": ("R", "&", "D"),
    "mg/kg": ("mg", "/", "kg"),
    "ER+/-": ("ER", "+", "/", "-"),
}
# one-token mutations by class: digit, decimal separator, exponent sign, operator flip, dropped charge,
# hyphen -> space (two items), Greek letter, case
MUTATIONS: dict[str, tuple[str, ...]] = {
    "0.05": ("0.005", ".05"),
    "1.5": ("15",),
    "-0.5": ("0.5",),
    "1,000": ("1.000", "1000"),
    "1e-5": ("1e-6", "1e5"),
    "<": (">", "<=", "≤"),
    "<=": ("=", "<"),
    "=": ("!=", "<="),
    "≥": (">=", ">"),
    "~": ("≈",),
    "Na+": ("Na",),
    "Na/K": ("Na",),
    "10^-6": ("10^5",),
    "GLP-1": ("GLP 1",),
    "β2": ("beta2",),
    "reduced": ("Reduced", "increased"),
    "mg": ("Mg",),
    "10 °C": ("10 C",),
    "R&D": ("R D",),
}
EXTRA_TOKENS: dict[str, tuple[str, ...]] = {"GLP 1": ("GLP", "1"), "10 C": ("10", "C"), "R D": ("R", "D")}
# items whose tokens are separated by a space inside the item (all other multi-token items are glued)
SPACED: frozenset[str] = frozenset({"GLP 1", "10 C", "R D", "10 °C"})
# every separator ends in a space or "(" so a sign or operator can never touch the next item
SEPARATORS: tuple[str, ...] = (" ", ", ", "; ", " (", ") ")


def _item_tokens(item: str) -> tuple[str, ...]:
    return ITEMS.get(item) or EXTRA_TOKENS[item]


def _join(items: list[str], seps: list[str]) -> str:
    out = items[0]
    for sep, item in zip(seps, items[1:], strict=True):
        out += sep + item
    return out


def _flat(items: list[str]) -> list[str]:
    return [tok for item in items for tok in _item_tokens(item)]


def _touch_left(items: list[str]) -> list[bool]:
    """Per flattened token: does it touch the previous token? Only inside a glued multi-token item."""
    return [i > 0 and item not in SPACED for item in items for i in range(len(_item_tokens(item)))]


def _oracle(quote: list[str], text: list[str], touch: list[bool]) -> bool:
    """Contiguous run of tokens that touches no neighbour on either side."""
    n = len(quote)
    return any(
        text[i : i + n] == quote and not touch[i] and (i + n == len(text) or not touch[i + n])
        for i in range(len(text) - n + 1)
    )


Case = tuple[str, str, list[str], list[str], list[bool]]
"""quote, text, quote tokens, text tokens, touch-left flags of the text tokens"""


@st.composite
def _case(draw: st.DrawFn, *, mutate: bool) -> Case:
    items = draw(st.lists(st.sampled_from(sorted(ITEMS)), min_size=1, max_size=25))
    start = draw(st.integers(0, len(items) - 1))
    length = draw(st.integers(1, min(6, len(items) - start)))
    window = items[start : start + length]
    if mutate:
        targets = [i for i, item in enumerate(window) if item in MUTATIONS]
        assume(targets)
        at = draw(st.sampled_from(targets))
        window = [*window[:at], draw(st.sampled_from(MUTATIONS[window[at]])), *window[at + 1 :]]
        if draw(st.booleans()):  # plant the mutated window elsewhere: repeats are where locators break
            pos = draw(st.integers(0, len(items)))
            items = [*items[:pos], *window, *items[pos:]]
    text_seps = draw(st.lists(st.sampled_from(SEPARATORS), min_size=len(items) - 1, max_size=len(items) - 1))
    quote_seps = draw(
        st.lists(st.sampled_from(SEPARATORS), min_size=len(window) - 1, max_size=len(window) - 1)
    )
    return _join(window, quote_seps), _join(items, text_seps), _flat(window), _flat(items), _touch_left(items)


def _cleaned(raw: str) -> CleanedText:
    text = clean_abstract(raw)
    assert text == raw  # generated texts are already clean, so the hand-written tokens apply
    return text


@given(_case(mutate=False))
def test_p1_p2_window_is_located_under_any_separators(case: Case) -> None:
    quote, raw, quote_tokens, _, _ = case
    text = _cleaned(raw)
    span = locate_quote(quote, text)
    assert span is not None
    assert [t.value for t in _tokens(span.of(text))] == quote_tokens


@given(_case(mutate=True))
def test_p1_p3_one_token_mutation_matches_the_oracle(case: Case) -> None:
    quote, raw, quote_tokens, text_tokens, touch = case
    text = _cleaned(raw)
    span = locate_quote(quote, text)
    assert (span is not None) is _oracle(quote_tokens, text_tokens, touch)
    if span is not None:
        assert [t.value for t in _tokens(span.of(text))] == quote_tokens


@given(_case(mutate=False))
def test_p4_span_is_on_token_boundaries(case: Case) -> None:
    quote, raw, _, _, _ = case
    text = _cleaned(raw)
    span = locate_quote(quote, text)
    assert span is not None
    assert span.end <= len(text)
    assert span.start in {t.start for t in _tokens(text)}
    assert span.end in {t.end for t in _tokens(text)}


def _nfkc_free_of_markup(ch: str) -> bool:
    return not any(c in "&<>" for c in unicodedata.normalize("NFKC", ch))


_MARKUP = (
    "<p>",
    "</p>",
    "<h4>",
    "</h4>",
    "<i>",
    "</i>",
    "<sup>",
    "</sup>",
    "<sub>",
    "</sub>",
    "<br/>",
    "<!-- c -->",
)


@given(
    st.lists(
        st.one_of(st.sampled_from(_MARKUP), st.characters(codec="utf-8").filter(_nfkc_free_of_markup)),
        max_size=60,
    ).map("".join)
)
def test_p5_cleaning_is_idempotent_without_entities(raw: str) -> None:
    once = clean_abstract(raw)
    assert clean_abstract(once) == once
