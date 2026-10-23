"""[TEST SUPPORT] One valid instance of every pipeline event, and a fixed clock, for event tests."""

from datetime import UTC, datetime, timedelta

from bio_claim_check.common.scripted_clock import ScriptedClock
from bio_claim_check.engine.events.llm_events import (
    LlmCallFailed,
    LlmCallFinished,
    LlmCallStarted,
    LlmRepairRequested,
    LlmRetryScheduled,
)
from bio_claim_check.engine.events.pipeline_event import ModelRef, PipelineEvent
from bio_claim_check.engine.events.stage_events import StageFailed, StageFinished, StageStarted

T0 = datetime(2026, 1, 1, tzinfo=UTC)
MODEL = ModelRef(provider="foundry_openai", deployment="d", model_version="v1")
HASH = "0" * 64


def stepping_clock() -> ScriptedClock:
    return ScriptedClock(T0, timedelta(seconds=1))


def one_of_each() -> tuple[PipelineEvent, ...]:
    return (
        StageStarted(at=T0, stage="ping"),
        StageFinished(at=T0, stage="ping"),
        StageFailed(at=T0, stage="ping", error_code="llm.call_failed"),
        LlmCallStarted(
            at=T0, agent="ping", model=MODEL, attempt=1, repeat_idx=0, request_hash=HASH, prompt_sha256=None
        ),
        LlmCallFinished(
            at=T0,
            agent=None,
            model=MODEL,
            attempt=1,
            finish_reason="stop",
            cache_hit=False,
            served_model="m",
            input_tokens=3,
            output_tokens=2,
            reasoning_tokens=None,
            cached_input_tokens=0,
        ),
        LlmRepairRequested(at=T0, agent="ping", model=MODEL, attempt=1, problems=(("ok", "missing"),)),
        LlmCallFailed(
            at=T0,
            agent="ping",
            model=MODEL,
            error_code="llm.transport",
            kind=None,
            attempts=1,
            unmeasured=True,
        ),
        LlmRetryScheduled(at=T0, model=MODEL, transport_attempt=1, status=429, delay_s=1.0),
    )
