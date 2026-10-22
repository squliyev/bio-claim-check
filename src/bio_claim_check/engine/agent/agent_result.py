"""[RING:engine/agent] What an agent run returns: the output, the agent's name and every attempt.

Why: callers (S10 answerer, S12 verifier, S11 ledger) need the validated output and its provenance
(responses, spend, `PromptRef` on the request) together, labelled with the agent that produced them.
Must not: hold provider objects or mutable state.
"""

from dataclasses import dataclass

from bio_claim_check.engine.pipeline.invocation import Invocation


@dataclass(frozen=True, slots=True)
class AgentResult[P, T]:
    """The validated output, the agent that produced it, and every attempt's responses and spend."""

    agent: str
    output: T
    invocation: Invocation[P]
