"""[RING:features/verify] The port the verify slice owns: judge one claim against one cited paper.

Why: one call per (claim, source) pair keeps the verifier context-isolated (it sees one claim, one
abstract and the rule pack, nothing else) and makes every pair a separate, countable outcome.
Implementations subclass this base and sit beside it, named by backend (ADR 0007): `scripted_verifier`
and `llm_verifier` (S12a). Replaced the structural `ports.Verifier` Protocol in S05b.
Failure contract: a problem with this pair's output is returned as a counted `VerifierFailure`; any
other error raises and stops the run (I70).
Must not: hold any implementation, or import one.

No LLM is involved in this module.
"""

from abc import ABC, abstractmethod

from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.rulepack import RulePack
from bio_claim_check.features.contracts.verdict import Claim, Verdict, VerifierFailure


class BaseVerifier(ABC):
    """Judges whether one paper supports one claim."""

    @abstractmethod
    def verify(self, claim: Claim, paper: Paper, rules: RulePack) -> Verdict | VerifierFailure:
        """Judge `claim` against `paper` using `rules`.

        Returns:
            A Verdict built with `Verdict.finalise` against `paper.abstract`, or a counted failure for a
            pair-level problem. Anything not attributable to the pair raises.
        """
