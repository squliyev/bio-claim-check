"""The one usage fold (I67): per model, cache hits never live, unknown usage never counted as 0 tokens."""

from datetime import datetime

import pytest
from tests.support.events import HASH, MODEL, T0

from bio_claim_check.engine.events.call_tally import CallTally, paired_attempts, summed, tally_calls
from bio_claim_check.engine.events.llm_events import (
    LlmCallFailed,
    LlmCallFinished,
    LlmCallStarted,
    LlmRetryScheduled,
)
from bio_claim_check.engine.events.pipeline_event import ModelRef
from bio_claim_check.engine.events.stage_events import StageStarted

pytestmark = pytest.mark.unit

OTHER = ModelRef(provider="foundry_anthropic", deployment="e", model_version="v2")


def started(model: ModelRef = MODEL, agent: str = "a") -> LlmCallStarted:
    return LlmCallStarted(
        at=T0, agent=agent, model=model, attempt=1, repeat_idx=0, request_hash=HASH, prompt_sha256=None
    )


def finished(
    *,
    cache_hit: bool = False,
    tokens: int = 5,
    reasoning: int | None = 1,
    model: ModelRef = MODEL,
    at: datetime = T0,
) -> LlmCallFinished:
    return LlmCallFinished(
        at=at,
        agent="a",
        model=model,
        attempt=1,
        finish_reason="stop",
        cache_hit=cache_hit,
        served_model="m",
        input_tokens=tokens,
        output_tokens=tokens,
        reasoning_tokens=reasoning,
        cached_input_tokens=0,
    )


def failed(*, unmeasured: bool, model: ModelRef = MODEL) -> LlmCallFailed:
    return LlmCallFailed(
        at=T0,
        agent="a",
        model=model,
        error_code="llm.transport",
        kind=None,
        attempts=1,
        unmeasured=unmeasured,
    )


def test_tokens_are_summed_over_live_finished_attempts_only() -> None:
    events = (
        StageStarted(at=T0, stage="answer"),
        started(),
        finished(tokens=10),
        started(),
        finished(cache_hit=True, tokens=1000),
        started(),
        finished(tokens=5, reasoning=None),
    )
    assert list(tally_calls(events).items()) == [
        (
            MODEL,
            CallTally(
                finished_attempts=3,
                cache_hits=1,
                measured_input_tokens=15,
                measured_output_tokens=15,
                measured_reasoning_tokens=1,
                reasoning_unreported=1,
            ),
        )
    ]
    assert tally_calls(events)[MODEL].finished_live_attempts == 2


def test_failures_retries_and_open_starts_are_counted_apart_never_as_tokens() -> None:
    events = (
        started(),
        LlmRetryScheduled(at=T0, model=MODEL, transport_attempt=1, status=429, delay_s=1.0),
        failed(unmeasured=True),
        started(),
        failed(unmeasured=False),
        started(),  # the process stopped before this attempt ended
    )
    assert list(tally_calls(events).items()) == [
        (MODEL, CallTally(failed_calls=2, unmeasured_attempts=2, transport_retries=1))
    ]


def test_usage_is_kept_per_model_in_first_seen_order_and_summed_on_request() -> None:
    events = (started(OTHER), finished(model=OTHER), started(), finished(tokens=2))
    tallies = tally_calls(events)
    assert list(tallies) == [OTHER, MODEL]
    total = summed(tallies.values())
    assert (total.finished_attempts, total.measured_input_tokens) == (2, 7)


def test_pairing_is_per_agent_and_model_and_never_raises() -> None:
    a, b = started(agent="a"), started(agent="b")
    end = finished()
    orphan = failed(unmeasured=True)
    pairs = list(paired_attempts((orphan, a, b, end, a)))
    assert pairs == [(a, end), (b, None), (a, None)]


def test_a_repeated_start_closes_the_earlier_one_as_never_ended() -> None:
    first, second = started(), started()
    end = finished()
    assert list(paired_attempts((first, second, end))) == [(first, None), (second, end)]
