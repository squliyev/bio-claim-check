"""[RING:features/traps] Rule-floor traps: one mechanical edit to a parent that changes what it states.

Why: a model-written trap measures one kind of misreading, but a verifier must also notice a flipped
direction, a flipped comparison or a tenfold dose. These edits need no model. An edit is made only when
exactly one site in the parent matches its rule; zero or several sites means no trap (no guessing which one
matters). The author still confirms every result in the audit sheet, since a swap can be meaningless (for
example "lower" inside a name).
Must not: edit more than one site, or call a model.

No LLM is involved in this module.
"""

import re
from decimal import Decimal
from typing import Final

from bio_claim_check.common.models import NonBlankStr, ValidatedModel
from bio_claim_check.features.traps.models import FloorRule

_DIRECTION_PAIRS: Final = (
    ("increased", "decreased"),
    ("increase", "decrease"),
    ("increases", "decreases"),
    ("higher", "lower"),
    ("improved", "worsened"),
    ("improves", "worsens"),
    ("more", "less"),
    ("greater", "smaller"),
    ("reduced", "raised"),
)
_SWAP: Final = {a: b for x, y in _DIRECTION_PAIRS for a, b in ((x, y), (y, x))}
_DIRECTION: Final = re.compile(
    r"\b(" + "|".join(sorted(_SWAP, key=len, reverse=True)) + r")\b", re.IGNORECASE
)
_OPERATOR_SWAP: Final = {"<": ">", ">": "<", "≤": "≥", "≥": "≤"}
_OPERATOR: Final = re.compile(r"[<>≤≥]")
_DOSE: Final = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)(\s*)(mg/kg|mg|µg|μg|IU)\b")


class FloorTrap(ValidatedModel):
    rule: FloorRule
    claim: NonBlankStr


def _cased(word: str, like: str) -> str:
    if like.isupper():
        return word.upper()
    return word.capitalize() if like[:1].isupper() else word


def _direction(text: str) -> str | None:
    found = list(_DIRECTION.finditer(text))
    if len(found) != 1:
        return None
    m = found[0]
    return text[: m.start()] + _cased(_SWAP[m.group(1).lower()], m.group(1)) + text[m.end() :]


def _operator(text: str) -> str | None:
    found = list(_OPERATOR.finditer(text))
    if len(found) != 1:
        return None
    m = found[0]
    return text[: m.start()] + _OPERATOR_SWAP[m.group(0)] + text[m.end() :]


def _dose(text: str) -> str | None:
    found = list(_DOSE.finditer(text))
    if len(found) != 1:
        return None
    m = found[0]
    tenfold = format((Decimal(m.group(1)) * 10).normalize(), "f")
    return text[: m.start()] + tenfold + m.group(2) + m.group(3) + text[m.end() :]


def mutate(parent: str) -> tuple[FloorTrap, ...]:
    """Every rule-floor trap of `parent`, in rule order (direction, operator, dose)."""
    edits: tuple[tuple[FloorRule, str | None], ...] = (
        ("direction", _direction(parent)),
        ("operator", _operator(parent)),
        ("dose", _dose(parent)),
    )
    return tuple(FloorTrap(rule=rule, claim=claim) for rule, claim in edits if claim is not None)
