"""[RING:features/retrieval] The search input contract and the exact query string sent to Europe PMC.

Why: every literature source must reject the same bad input (blank question, control characters, a limit
outside [1, 100]), and implementations may not import each other, so the rule lives here once.
The query is the user's text verbatim, in Europe PMC search syntax by design (field queries such as
`TITLE:x` stay usable); the post-filter in `citable`, not this string, guarantees citability (ADR 0008).
Must not: rewrite, escape or expand the question.

No LLM is involved in this module.
"""

import unicodedata

from bio_claim_check.features.retrieval.citable import QUERY_FILTERS

MAX_LIMIT = 100
"""Top-k needs one page of results; paging (`cursorMark`) is out of scope until a caller needs more."""


def validate_search(question: str, limit: int) -> None:
    """Raise `ValueError` for input no implementation accepts."""
    if not question.strip():
        raise ValueError("the question must not be blank")
    if any(unicodedata.category(c) == "Cc" for c in question):
        raise ValueError("the question must not contain control characters")
    if isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}, got {limit!r}")


def build_query(question: str) -> str:
    """The exact query sent: `(<question>) AND <citable filters>`."""
    return f"({question}) AND {QUERY_FILTERS}"
