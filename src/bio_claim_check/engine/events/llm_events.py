"""[RING:engine/events] What happened to each LLM call, without what was said.

Why: spend, finish reasons, repairs and transport retries are the numbers a reviewer checks first. A
*logical attempt* is one runner turn (the first call, or the one repair): it emits exactly one
`LlmCallStarted` and one `LlmCallFinished`, or the call's single `LlmCallFailed` (I60). A *transport
retry* happens inside a backend, within one logical attempt, and emits `LlmRetryScheduled`.
`LlmCallFailed.unmeasured` says the failing attempt's client call raised after it may have reached the
provider (a transport error, an unexpected response, a provider rejection, a cache write after a live
call), so its usage is unknown: counted, never summed as 0 (I67).
Usage fields mirror `engine.llm.Usage` (reasoning ⊆ output, cached ⊆ input, reasoning None when
unreported); a parity test keeps them in step (I58).
Must not: carry message text, model output, validator messages, payloads, endpoints or keys (I59);
only ids, counts, codes, hashes and validation locations.

No LLM is involved in this module.
"""

from typing import Annotated, Literal

from pydantic import Field

from bio_claim_check.common.models import NonBlankStr, Sha256Hex
from bio_claim_check.engine.events.pipeline_event import ModelRef, PipelineEvent

Count = Annotated[int, Field(strict=True, ge=0)]
Attempt = Annotated[int, Field(strict=True, ge=1)]


class LlmCallStarted(PipelineEvent):
    type: Literal["llm.call_started"] = "llm.call_started"
    agent: NonBlankStr | None
    model: ModelRef
    attempt: Attempt
    repeat_idx: Count
    request_hash: Sha256Hex
    prompt_sha256: Sha256Hex | None


class LlmCallFinished(PipelineEvent):
    type: Literal["llm.call_finished"] = "llm.call_finished"
    agent: NonBlankStr | None
    model: ModelRef
    attempt: Attempt
    finish_reason: NonBlankStr
    cache_hit: bool
    served_model: NonBlankStr | None
    input_tokens: Count
    output_tokens: Count
    reasoning_tokens: Count | None
    cached_input_tokens: Count


class LlmRepairRequested(PipelineEvent):
    type: Literal["llm.repair_requested"] = "llm.repair_requested"
    agent: NonBlankStr | None
    model: ModelRef
    attempt: Attempt
    problems: tuple[tuple[str, str], ...]  # (location, error type) only, never the message


class LlmCallFailed(PipelineEvent):
    type: Literal["llm.call_failed"] = "llm.call_failed"
    agent: NonBlankStr | None
    model: ModelRef
    error_code: NonBlankStr
    kind: NonBlankStr | None
    attempts: Count  # 0 when it failed before reaching the client (e.g. a processor contract error)
    unmeasured: bool  # the failing attempt may have reached the provider, and its usage is unknown


class LlmRetryScheduled(PipelineEvent):
    type: Literal["llm.retry_scheduled"] = "llm.retry_scheduled"
    model: ModelRef
    transport_attempt: Attempt
    status: Annotated[int, Field(strict=True, ge=100, le=599)] | None
    delay_s: Annotated[float, Field(ge=0, allow_inf_nan=False)]
