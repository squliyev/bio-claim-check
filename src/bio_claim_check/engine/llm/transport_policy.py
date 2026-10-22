"""[RING:engine/llm] Deterministic transport retries and failure classification, shared by both backends.

Why: retries decide what a run is billed and how long it waits, so they must be predictable and
testable without a network (I55). Each backend turns its SDK's exception into a neutral
`TransportFailure`; this module decides: retry (408, 429, 500, 502, 503, Anthropic's 529 "overloaded",
and a refused connection, after 1, 2, 4 s or the provider's `retry-after-ms`/`Retry-After`, capped at
60 s), a prompt filter (HTTP 400 with code `content_filter`), a permanent rejection, or give up. A
failure after the request may have reached the provider (a timeout, a dropped connection, a gateway
timeout 504) is never retried: the provider may have processed and billed it, and a retry would bill
again and hide that spend. SDK retries
are switched off in `app`, so this is the only retry loop. No jitter: two runs wait the same.
Must not: import a provider driver, read the wall clock (sleep is injected), or put a response body,
header value or message into an error.

Pure logic: makes no provider call. (It is LLM vocabulary, so it does not carry the
ADR 0003 deterministic marker.)
"""

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, cast

from bio_claim_check.engine.llm.errors import LlmPromptFilteredError, LlmProviderError, LlmTransportError

RETRY_DELAYS: Final = (1.0, 2.0, 4.0)
MAX_RETRY_AFTER: Final = 60.0
RETRY_STATUSES: Final = frozenset({408, 429, 500, 502, 503, 529})  # 529: Anthropic "overloaded"
MAYBE_BILLED_STATUSES: Final = frozenset({504})  # the gateway gave up; the model may still have run
CONTENT_FILTER_CODE: Final = "content_filter"
MAYBE_BILLED_REASON: Final = "may have reached the provider (not retried: it may have been billed)"


class Outcome(StrEnum):
    RETRY = "retry"
    PROMPT_FILTERED = "prompt_filtered"
    REJECT = "reject"
    GIVE_UP = "give_up"


@dataclass(frozen=True, slots=True)
class TransportFailure:
    """One failed transport attempt, stripped to what the policy needs (no body, no message)."""

    status: int | None  # None: no HTTP response (connection failure or timeout)
    headers: Mapping[str, str] = field(default_factory=dict[str, str])
    provider_code: str | None = None
    maybe_billed: bool = False  # the request may have reached the provider (timeout, dropped connection)


def classify(failure: TransportFailure) -> Outcome:
    if failure.maybe_billed or failure.status in MAYBE_BILLED_STATUSES:
        return Outcome.GIVE_UP
    if failure.status is None:
        return Outcome.RETRY
    if failure.status == 400 and failure.provider_code == CONTENT_FILTER_CODE:
        return Outcome.PROMPT_FILTERED
    if failure.status in RETRY_STATUSES:
        return Outcome.RETRY
    return Outcome.REJECT


def _seconds(value: str | None, scale: float) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value.strip()) * scale
    except ValueError:
        return None  # e.g. an HTTP-date: fall back to our own schedule rather than parse a clock
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def retry_delay(retry: int, headers: Mapping[str, str]) -> float:
    """Seconds to wait before retry number `retry` (0-based): the provider's hint if valid, capped."""
    lowered = {k.lower(): v for k, v in headers.items()}
    hinted = _seconds(lowered.get("retry-after-ms"), 0.001)
    if hinted is None:
        hinted = _seconds(lowered.get("retry-after"), 1.0)
    return min(MAX_RETRY_AFTER, RETRY_DELAYS[retry] if hinted is None else hinted)


def retry_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Only the retry hints from a response's headers; nothing else is carried past the backend."""
    return {k.lower(): v for k, v in headers.items() if k.lower() in {"retry-after", "retry-after-ms"}}


def provider_error_code(body: object) -> str | None:
    """The machine-readable error code from an error body (`{"error": {"code"|"type": …}}` or flat)."""
    if not isinstance(body, dict):
        return None
    outer = cast("dict[str, object]", body)
    inner = outer.get("error", outer)
    if not isinstance(inner, dict):
        return None
    inner_map = cast("dict[str, object]", inner)
    for key in ("code", "type"):
        if isinstance(value := inner_map.get(key), str) and value.strip():
            return value
    return None


def _no_retry_hook(_transport_attempt: int, _status: int | None, _delay: float) -> None:
    return None


def with_retries[T](
    attempt: Callable[[], T | TransportFailure],
    *,
    deployment: str,
    sleep: Callable[[float], None],
    on_retry: Callable[[int, int | None, float], None] = _no_retry_hook,
) -> T:
    """Call `attempt` until it returns a value, retrying per the policy; raise a typed error otherwise.

    `on_retry(transport_attempt, status, delay)` runs before each sleep (the backend emits an event).
    """
    retries = 0
    while True:
        result = attempt()
        if not isinstance(result, TransportFailure):
            return result
        outcome = classify(result)
        if outcome is Outcome.PROMPT_FILTERED:
            raise LlmPromptFilteredError(deployment=deployment)
        if outcome is Outcome.REJECT and result.status is not None:
            raise LlmProviderError(
                deployment=deployment, status=result.status, provider_code=result.provider_code
            )
        if outcome is not Outcome.RETRY or retries == len(RETRY_DELAYS):
            raise LlmTransportError(
                deployment=deployment,
                status=result.status,
                attempts=retries + 1,
                reason=MAYBE_BILLED_REASON if classify(result) is Outcome.GIVE_UP else "failed",
            )
        delay = retry_delay(retries, result.headers)
        retries += 1
        on_retry(retries, result.status, delay)
        sleep(delay)
