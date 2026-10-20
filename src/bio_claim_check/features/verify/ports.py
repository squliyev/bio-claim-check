"""[RING:features/verify] The port the verify slice owns: judge one claim against one cited paper.

Why: one call per (claim, source) pair keeps the verifier context-isolated (it sees one claim, one
abstract and the rule pack, nothing else) and makes every pair a separate, countable outcome.
Must not: hold any implementation.
"""

from typing import Protocol

from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.rulepack import RulePack
from bio_claim_check.features.contracts.verdict import Claim, Verdict, VerifierFailure


class Verifier(Protocol):
    """Judges whether one paper supports one claim."""

    def verify(self, claim: Claim, paper: Paper, rules: RulePack) -> Verdict | VerifierFailure:
        """A Verdict built with `Verdict.finalise` against `paper.abstract`, or a counted failure."""
        raise NotImplementedError
