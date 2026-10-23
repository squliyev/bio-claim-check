"""[RING:features/verify] What the verifier agent is given: one claim, one paper, the rule pack.

Why: the payload is the isolation boundary (I69). The verifier sees the claim's text, the paper's title
and cleaned abstract and the rule pack, and nothing else from the run: not the question, other claims or
papers, nor any id. Keeping it this small makes the boundary a type, not a promise.
Must not: gain a field that carries run context (the question, other claims, ids, MeSH or retrieval
metadata).

No LLM is involved in this module.
"""

from dataclasses import dataclass

from bio_claim_check.common.text import CleanedText
from bio_claim_check.features.contracts.rulepack import RulePack


@dataclass(frozen=True, slots=True)
class VerifyPayload:
    """One (claim, source) pair as the verifier sees it."""

    claim: str
    title: str
    abstract: CleanedText
    rules: RulePack
