"""[RING:features/checks] Claims that lean on context the verifier never sees (P2, flag half).

Why: each claim is verified alone against one abstract. A claim such as "This drug slowed decline" or
"These findings suggest a benefit" points at something outside itself, so the verifier cannot know what
it is about, and a pass would be unearned. The check flags such claims so the answer mode is measured
as it is.
Must not: rewrite a claim (the maintainer chose flag only in S10; a rewrite needs an audit trail), judge
meaning, or flag a reference whose antecedent sits inside the same claim. It is deliberately narrow:
only phrases that can have no antecedent within one claim are flagged.

No LLM is involved in this module.
"""

import re
from typing import Final

from bio_claim_check.features.contracts.answer import Answer
from bio_claim_check.features.contracts.finding import Finding, FindingKind

_OPENING: Final = re.compile(r"^\W*(?P<ref>this|these|those|such|it|they|its|their)\b", re.IGNORECASE)
"""A claim that opens with a demonstrative or pronoun: there is nothing before it inside the claim."""

_ANYWHERE: Final = re.compile(
    r"\b(?P<ref>"
    r"the\s+(?:aforementioned|above[- ]mentioned|former|latter|same\s+(?:drug|study|trial|compound))"
    r"|the\s+authors"
    r"|as\s+(?:mentioned|noted|stated|discussed|described|shown)\s+(?:above|earlier|previously|before)"
    r"|(?:above|previous|preceding)\s+(?:claim|sentence|paragraph|section|point)"
    r")\b",
    re.IGNORECASE,
)
"""Phrases that point outside the claim wherever they occur."""


def dangling_claims(answer: Answer) -> tuple[Finding, ...]:
    """One finding per claim that refers to something outside itself, in claim order."""
    findings: list[Finding] = []
    for claim in answer.claims:
        match = _OPENING.search(claim.text) or _ANYWHERE.search(claim.text)
        if match is not None:
            findings.append(
                Finding(
                    kind=FindingKind.DANGLING_REFERENCE,
                    claim_id=claim.id,
                    source_id=None,
                    detail=f'"{match.group("ref")}" refers to something outside the claim',
                )
            )
    return tuple(findings)
