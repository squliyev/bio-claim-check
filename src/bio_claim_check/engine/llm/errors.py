"""[RING:engine/llm] The one typed failure of a structured LLM call, carrying what it cost.

Why: a failed call still costs money and still belongs in the denominators (FAILED stays counted, S16).
The error says which kind of failure it was, where the output failed validation, and the spend of every
attempt. It carries validation locations and error types only, never input values, so abstract text
cannot leak into logs through an exception.
Must not: map itself to a domain FailureKind (the feature owns that mapping, S12) or hold model output.

Pure values: makes no provider call. (It is LLM vocabulary, so it does not carry the
ADR 0003 deterministic marker.)
"""

from enum import StrEnum

from bio_claim_check.engine.llm.usage import Spend


class LlmFailureKind(StrEnum):
    INVALID_OUTPUT = "invalid_output"
    TRUNCATED = "truncated"
    CONTENT_FILTERED = "content_filtered"


class LlmCallError(Exception):
    """A structured call that produced no usable output."""

    def __init__(
        self,
        kind: LlmFailureKind,
        *,
        deployment: str,
        attempts: int,
        spend: Spend,
        validation: tuple[tuple[str, str], ...] = (),
    ) -> None:
        where = "; ".join(f"{loc}: {kind_}" for loc, kind_ in validation)
        detail = f" ({where})" if where else ""
        super().__init__(f"{deployment}: {kind} after {attempts} attempt(s){detail}")
        self.kind = kind
        self.deployment = deployment
        self.attempts = attempts
        self.spend = spend
        self.validation = validation
