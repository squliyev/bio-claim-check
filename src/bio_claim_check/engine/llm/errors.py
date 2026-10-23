"""[RING:engine/llm] The typed failures of an LLM call: the runner's, and the provider backends' (S09).

Why: a failed call still costs money and still belongs in the denominators (FAILED stays counted, S16).
`LlmCallError` says which kind of failure it was, where the output failed validation, and the spend of
every attempt. The backend errors (transport, rejection, prompt filter, unsupported request, unexpected
response) carry statuses, attempt counts and provider codes. None carries input values, model output or
provider message bodies, so abstract text cannot leak into logs through an exception.
Must not: map itself to a domain FailureKind (the feature owns that mapping, S12) or hold model output.

Pure values: makes no provider call. (It is LLM vocabulary, so it does not carry the
ADR 0003 deterministic marker.)
"""

from enum import StrEnum

from bio_claim_check.common.errors import BccError
from bio_claim_check.engine.llm.usage import Spend


class LlmFailureKind(StrEnum):
    INVALID_OUTPUT = "invalid_output"
    TRUNCATED = "truncated"
    CONTENT_FILTERED = "content_filtered"


class LlmCallError(BccError):
    """A structured call that produced no usable output."""

    code = "llm.call_failed"

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


class LlmTransportError(BccError):
    """The provider could not be reached, or kept failing transiently, after the backend's retries (I55).

    Carries numbers only: the last HTTP status (None for a connection failure or timeout) and how many
    transport attempts were made. Never the response body, which may echo the prompt.
    """

    code = "llm.transport"

    def __init__(self, *, deployment: str, status: int | None, attempts: int, reason: str) -> None:
        shown = "no response" if status is None else f"HTTP {status}"
        super().__init__(f"{deployment}: {reason} ({shown}) after {attempts} transport attempt(s)")
        self.deployment = deployment
        self.status = status
        self.attempts = attempts


class LlmProviderError(BccError):
    """The provider refused the request permanently (auth, not found, bad request): never retried.

    Carries the status and the provider's machine-readable error code only, never its message.
    """

    code = "llm.provider_rejected"

    def __init__(self, *, deployment: str, status: int, provider_code: str | None) -> None:
        super().__init__(f"{deployment}: rejected with HTTP {status} (code {provider_code or 'none'})")
        self.deployment = deployment
        self.status = status
        self.provider_code = provider_code


class LlmPromptFilteredError(BccError):
    """The provider's content filter rejected the prompt before producing anything (HTTP 400).

    No usage is reported for such a call, so the runner records it as *unmeasured* (never as 0 tokens)
    and fails it as `content_filtered`, counted like any other filtered call (I53).
    """

    code = "llm.prompt_filtered"

    def __init__(self, *, deployment: str) -> None:
        super().__init__(f"{deployment}: the prompt was rejected by the provider's content filter")
        self.deployment = deployment


class LlmRequestError(BccError, ValueError):
    """A request this backend cannot send faithfully (unknown param, a seed, a non-strict schema)."""

    code = "llm.unsupported_request"


class LlmUnexpectedResponseError(BccError):
    """A provider response in a shape the codec does not know: fail closed, never guess (I53)."""

    code = "llm.unexpected_response"


class LlmBudgetExceededError(BccError):
    """The command already made its maximum number of live LLM calls; this one was not sent (S11)."""

    code = "llm.budget_exceeded"
