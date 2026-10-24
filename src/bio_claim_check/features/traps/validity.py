"""[RING:features/traps] The validity gate: drafted claims that cannot be used are excluded, with a reason.

Why: a trap that copies the abstract tests string matching, not reading; a trap that echoes a rule-pack
example tests memory of the prompt (the contamination check, I77, ADR 0006 follow-up); a claim longer than
`MAX_CLAIM_WORDS` is a summary, not a claim. Copying is checked against the cleaned abstract here, at
generation time; close paraphrase is the author's call in the audit sheet, because CI has no abstracts.
Contamination needs no abstract, so CI recomputes it on the committed set (`contamination`).
Must not: judge whether a claim is supported or overstated (the author does), or call a model.

No LLM is involved in this module.
"""

import re
from collections.abc import Iterable
from typing import Final

from bio_claim_check.common.text import CleanedText
from bio_claim_check.features.contracts.rulepack import RulePack
from bio_claim_check.features.traps.models import MAX_CLAIM_WORDS

COPY_RUN: Final = 8
"""A claim sharing this many consecutive words with the abstract copies it."""

CONTAMINATION_RUN: Final = 6
"""A claim sharing this many consecutive words with a rule-pack example echoes the prompt (I77)."""

_WORD: Final = re.compile(r"\w+")


def words(text: str) -> list[str]:
    """Case-folded word tokens; punctuation and spacing never hide a shared run."""
    return _WORD.findall(text.casefold())


def _runs(tokens: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def shares_run(claim: str, others: Iterable[str], n: int) -> bool:
    """Whether `claim` and any of `others` share `n` consecutive words."""
    mine = _runs(words(claim), n)
    return any(mine & _runs(words(other), n) for other in others)


def example_texts(pack: RulePack) -> tuple[str, ...]:
    """Every rule-pack example claim and excerpt: the text the verifier's prompt shows."""
    return tuple(t for rule in pack.rules for ex in rule.examples for t in (ex.claim, ex.source_excerpt))


def contamination(claim: str, pack: RulePack) -> list[str]:
    """[] or one problem: the claim echoes a rule-pack example (I77)."""
    if shares_run(claim, example_texts(pack), CONTAMINATION_RUN):
        return [f"shares {CONTAMINATION_RUN} consecutive words with a rule-pack example"]
    return []


def claim_problems(claim: str, abstract: CleanedText, pack: RulePack) -> list[str]:
    """[] when one drafted claim is usable; otherwise one line per problem."""
    problems: list[str] = []
    if len(claim.split()) > MAX_CLAIM_WORDS:
        problems.append(f"longer than {MAX_CLAIM_WORDS} words")
    if shares_run(claim, (abstract,), COPY_RUN):
        problems.append(f"copies {COPY_RUN} consecutive words of the abstract")
    problems.extend(contamination(claim, pack))
    return problems


def pair_problems(parent: str, trap: str) -> list[str]:
    """[] when a trap differs from its parent (case and spacing aside)."""
    return ["the trap repeats its parent"] if words(parent) == words(trap) else []
