"""[RING:common] Text primitives that every verdict depends on.

`clean_abstract` produces the ONE text that the LLM reads, the checks match against and the UI
highlights. `locate_quote` proves a quoted piece of evidence is in that text, by position. It fails
closed: if any word, number, sign, operator or exponent differs, the result is None. `near_match`
exists only to route a near miss to human review; it can never make evidence "located" (ADR 0005).

Why tokens and not one regex: a regex that joins words with "any punctuation" lets `1.5` match `15`
and `= 0.05` match `<= 0.05`. Here both sides are cut into the same tokens (numbers, operators, words)
and the quote must equal a contiguous run of the text's tokens, compared exactly (case included).

No LLM is involved in this module. Offsets are Python str indices (code points), not UTF-16.
"""

import html
import re
import unicodedata
from dataclasses import dataclass
from typing import Final, NewType

from rapidfuzz import fuzz

CleanedText = NewType("CleanedText", str)
"""Text produced by `clean_abstract`. A static marker: pyright rejects a plain str where it is required."""

NEAR_MATCH_THRESHOLD: Final = 90.0
"""Minimum rapidfuzz partial-ratio for a near match (routing only; re-checked on dev data in S12)."""

NEAR_MIN_TOKENS: Final = 3
"""Shorter quotes never near-match, so they cannot flood review with chance resemblances."""


@dataclass(frozen=True, slots=True)
class Span:
    """A half-open [start, end) range of code points in a `CleanedText`."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if not 0 <= self.start < self.end:
            raise ValueError(f"invalid span [{self.start}, {self.end})")

    def of(self, text: CleanedText) -> str:
        """The covered substring; raises if the span does not fit the text."""
        if self.end > len(text):
            raise ValueError(f"span [{self.start}, {self.end}) exceeds text length {len(text)}")
        return text[self.start : self.end]


@dataclass(frozen=True, slots=True)
class NearMatch:
    """An approximate region. It only routes a claim to needs-review; it is never evidence."""

    score: float
    span: Span


# ---------------------------------------------------------------- cleaning

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_PREFIX = r"(?:[a-zA-Z][\w.-]*:)?"  # optional XML namespace, e.g. <jats:sup>
# attributes must have values (class="x"), so prose like "a <b and c> d" is never mistaken for a tag
_ATTRS = r"""(?:\s+[a-zA-Z_][\w:.-]*\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'<>=`]+))*\s*"""
_SUP = re.compile(rf"<{_PREFIX}sup{_ATTRS}>(.*?)</{_PREFIX}sup\s*>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(rf"</?{_PREFIX}([a-zA-Z][\w.-]*){_ATTRS}/?>")
_BLOCK_TAGS: Final = frozenset(
    {"h1", "h2", "h3", "h4", "h5", "h6", "p", "title", "br", "div", "li", "ul", "ol", "sec", "abstract"}
)
# Only known markup is stripped; an unknown `<x>` stays literal text, so cleaning never deletes prose.
_INLINE_TAGS: Final = frozenset(
    {"i", "b", "bold", "italic", "em", "strong", "sub", "sup", "u", "underline", "sc", "span", "a", "small"}
)
_SUPERSCRIPTS: Final = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")
_SUPERSCRIPT_RUN = re.compile("[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+")
_SOFT_HYPHEN: Final = "\u00ad"
# hyphen, non-breaking hyphen, en dash, minus sign, small/fullwidth hyphen-minus -> ASCII hyphen-minus;
# em dash and horizontal bar are prose -> space; tilde operator -> ASCII tilde.
_DASHES: Final = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2013": "-",
        "\u2212": "-",
        "\ufe63": "-",
        "\uff0d": "-",
        "\u2014": " ",
        "\u2015": " ",
        "\u223c": "~",
    }
)
_WHITESPACE = re.compile(r"\s+")


def _replace_tag(match: re.Match[str]) -> str:
    name = match.group(1).lower()
    if name in _BLOCK_TAGS:
        return " "
    return "" if name in _INLINE_TAGS else match.group(0)


def _strip_tags(markup: str) -> str:
    return _TAG.sub(_replace_tag, markup)


def _normalise_chars(text: str) -> str:
    """Steps shared by text and quote, so the two can never be normalised differently.

    Format characters are handled before NFKC: removing a soft hyphen afterwards could leave a base
    letter and a combining mark adjacent but uncomposed, so a second pass would change the text.
    """
    text = _SUPERSCRIPT_RUN.sub(lambda m: "^" + m.group(0).translate(_SUPERSCRIPTS), text)
    text = "".join(
        "" if ch == _SOFT_HYPHEN else " " if unicodedata.category(ch) == "Cf" else ch for ch in text
    )
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_DASHES)
    return _WHITESPACE.sub(" ", text).strip()


def clean_abstract(raw: str | None) -> CleanedText:
    """Europe PMC abstract markup -> the single text every later stage uses.

    Block tags (headings, paragraphs) become a space so `</h4>Methods` never glues words; inline tags
    vanish so `IC<sub>50</sub>` reads `IC50`. `<sup>` keeps its meaning as `^` (`10^5`, never `105`).
    Entities are unescaped only after tags are stripped, so an escaped `&lt;i&gt;` stays literal text.
    """
    if not raw:
        return CleanedText("")
    text = _COMMENT.sub("", raw)
    text = _SUP.sub(lambda m: "^" + _strip_tags(m.group(1)), text)
    text = _strip_tags(text)
    text = html.unescape(text)
    return CleanedText(_normalise_chars(text))


# ---------------------------------------------------------------- tokens and location

_IGNORED: Final = ".,;:!?()[]{}\"'\u2018\u2019\u201c\u201d"
"""Prose punctuation and brackets. Every OTHER non-space symbol is evidence (`+ / ^ % ° & ~ ...`)."""
_TOKEN = re.compile(
    r"(?<!\w)[-+]?(?:\d+(?:[.,]\d+)*|\.\d+)(?:[eE][-+]?\d+)?"  # number, with its sign and exponent
    r"|<=|>=|!=|=="  # multi-character operators
    rf"|[^\w\s{re.escape(_IGNORED)}]"  # any other symbol: fail closed on the unknown
    r"|\w+"  # word
)


@dataclass(frozen=True, slots=True)
class _Token:
    value: str
    start: int
    end: int


def _tokens(text: str) -> list[_Token]:
    return [_Token(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(text)]


def locate_quote(quote: str, text: CleanedText) -> Span | None:
    """The first position where the quote's tokens appear contiguously and exactly, else None.

    Punctuation and brackets between tokens are ignored; every token must be identical (case too).
    The match must also be a whole expression: no text token may touch either end, so `5 mg` is not
    found inside `5 mg/kg`, `5 cells` not inside `10^5 cells`, `ER+` not inside `ER+/-`.
    """
    wanted = [t.value for t in _tokens(_normalise_chars(quote))]
    if not wanted:
        return None
    found = _tokens(text)
    values = [t.value for t in found]
    n = len(wanted)
    for i in range(len(values) - n + 1):
        if values[i : i + n] == wanted and _detached(found, i, i + n):
            return Span(found[i].start, found[i + n - 1].end)
    return None


def _detached(tokens: list[_Token], first: int, stop: int) -> bool:
    """True if tokens[first:stop] touch no neighbouring token (a separator sits on both sides)."""
    left_free = first == 0 or tokens[first - 1].end < tokens[first].start
    right_free = stop == len(tokens) or tokens[stop].start > tokens[stop - 1].end
    return left_free and right_free


# ---------------------------------------------------------------- near match (routing only)


def _fold(text: str) -> str:
    """Lowercase without changing length (e.g. 'İ'.lower() is two code points), so offsets stay valid."""
    return "".join(low if len(low := ch.lower()) == 1 else ch for ch in text)


def _snap(start: int, end: int, tokens: list[_Token]) -> Span | None:
    """Widen [start, end) outward to whole tokens; None if it covers no token."""
    covered = [t for t in tokens if t.start < end and t.end > start]
    if not covered:
        return None
    return Span(covered[0].start, covered[-1].end)


def near_match(quote: str, text: CleanedText) -> NearMatch | None:
    """An approximate location for a quote that `locate_quote` rejected, for review only.

    A flipped word ("reduced" vs "increased") can still score high, which is exactly why a near match
    is never treated as located evidence (ADR 0005).
    """
    normalised = _normalise_chars(quote)
    if len(_tokens(normalised)) < NEAR_MIN_TOKENS or not text:
        return None
    alignment = fuzz.partial_ratio_alignment(
        _fold(normalised), _fold(text), score_cutoff=NEAR_MATCH_THRESHOLD
    )
    if alignment is None:
        return None
    # `dest_*` always indexes the second argument (the text), even when rapidfuzz swaps internally
    span = _snap(alignment.dest_start, alignment.dest_end, _tokens(text))
    return None if span is None else NearMatch(alignment.score, span)
