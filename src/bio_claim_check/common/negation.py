"""[RING:common] Whether a located evidence span sits in a sentence that contains a negation.

Why: a quote can be located verbatim and still mean the opposite of the claim, because the negation sits
just outside it ("significant reduction" quoted out of "no significant reduction", L18), or inside it
while the verifier misread it. Code must not judge meaning (ADR 0003), so this is deliberately crude and
conservative: any negation cue anywhere in the sentence (or sentences) holding the span counts. A false
"negated" only costs a human look (NEEDS_REVIEW); a false "clear" would cost a wrong PASSED.
Replaced the S05-S09 state where no detector existed and every located pair stayed NOT_RUN.
Must not: look at the claim, score meaning, or change without bumping `NEGATION_RULES` (stored on every
verdict, so a rule change can never silently re-score a stored report; ADR 0017).

No LLM is involved in this module.
"""

import re
from collections.abc import Iterator
from typing import Final

from bio_claim_check.common.text import CleanedText, Span

NEGATION_RULES: Final = 2
"""The version of the rules below. Bump it on any change to the cues or the sentence split.

v2 (S10 review): no sentence end after a common abbreviation ("Fig. S1"), which had cut a cue off.
"""

_SENTENCE_END: Final = re.compile(r"[.?!]\s+(?=[A-Z])")
"""A candidate sentence end: . ? ! followed by space and a capital."""

_ABBREVIATION: Final = re.compile(
    r"\b(?:fig|figs|tab|ref|refs|suppl|vs|al|e\.g|i\.e|cf|ca|approx|dr|no|nos|eq|vol|resp)\.$",
    re.IGNORECASE,
)
"""A dot ending one of these is not a sentence end. An unlisted abbreviation can only merge two sentences
(more text, so more cues): the safe direction."""


def _sentence_ends(text: CleanedText) -> Iterator[re.Match[str]]:
    for match in _SENTENCE_END.finditer(text):
        if not _ABBREVIATION.search(text, max(0, match.start() - 8), match.start() + 1):
            yield match


_CUE: Final = re.compile(
    r"\b(?:no|not(?!\s+only\b)|never|none|without|nor|neither|cannot"
    r"|unable\s+to|fail(?:s|ed)?\s+to|absence\s+of|lack(?:s|ed)?(?:\s+of)?"
    r"|non-?significant(?:ly)?)\b"
    r"|\b\w+n['\u2019]t\b",
    re.IGNORECASE,
)


def sentence_bounds(span: Span, text: CleanedText) -> tuple[int, int]:
    """The [start, end) of the sentence(s) holding `span`."""
    start = 0
    end = len(text)
    for match in _sentence_ends(text):
        if match.end() <= span.start:
            start = match.end()
        elif match.start() >= span.end - 1:
            end = match.start() + 1
            break
    return start, end


def is_negated(span: Span, text: CleanedText) -> bool:
    """True if a negation cue occurs anywhere in the sentence(s) holding `span` (before, inside or after)."""
    span.of(text)  # raises if the span does not fit the text
    start, end = sentence_bounds(span, text)
    return _CUE.search(text, start, end) is not None
