"""I60: each logical attempt emits one started and one finished event; failures emit once, before raising."""

from dataclasses import replace
from typing import override

import pytest
from pydantic import BaseModel, ConfigDict
from tests.support.events import stepping_clock
from tests.support.llm import request, response, spec

from bio_claim_check.engine.cache.in_memory_cache import InMemoryCache
from bio_claim_check.engine.cache.policy import CacheMode
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.in_memory_event_sink import InMemoryEventSink
from bio_claim_check.engine.events.llm_events import (
    LlmCallFailed,
    LlmCallFinished,
    LlmCallStarted,
    LlmRepairRequested,
)
from bio_claim_check.engine.llm.base_llm_client import BaseLlmClient
from bio_claim_check.engine.llm.caching_llm_client import CachingLlmClient
from bio_claim_check.engine.llm.errors import (
    LlmCallError,
    LlmFailureKind,
    LlmPromptFilteredError,
    LlmTransportError,
)
from bio_claim_check.engine.llm.llm_cache_key import llm_cache_key
from bio_claim_check.engine.llm.messages import FinishReason, LlmRequest, LlmResponse, PromptRef
from bio_claim_check.engine.llm.scripted_llm_client import ScriptedLlmClient
from bio_claim_check.engine.llm.usage import Usage
from bio_claim_check.engine.pipeline.base_request_processor import BaseRequestProcessor
from bio_claim_check.engine.pipeline.invocation import Invocation
from bio_claim_check.engine.pipeline.llm_runner import LlmRunner, ProcessorContractError

pytestmark = pytest.mark.unit

REF = PromptRef(name="p", version=1, sha256="a" * 64)


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool


def run(
    client: BaseLlmClient, processors: tuple[BaseRequestProcessor[str], ...] = ()
) -> tuple[InMemoryEventSink, Invocation[str] | BaseException]:
    sink = InMemoryEventSink()
    runner = LlmRunner[str, Out](
        client,
        spec(),
        Out,
        request_processors=processors,
        emitter=EventEmitter(sink, stepping_clock()),
        agent="judge",
    )
    try:
        _, inv = runner.run(Invocation(payload="claim", request=replace_prompt()))
    except LlmCallError as error:
        return sink, error
    return sink, inv


def replace_prompt() -> LlmRequest:
    return LlmRequest.model_validate({**request().model_dump(), "prompt": REF.model_dump()})


def kinds(sink: InMemoryEventSink) -> list[str]:
    return [e.type for e in sink.events]


def test_one_valid_call_is_started_then_finished_with_its_usage() -> None:
    usage = Usage(input_tokens=10, output_tokens=4, reasoning_tokens=None, cached_input_tokens=3)
    client = ScriptedLlmClient([replace_served(response(usage=usage))])
    sink, _ = run(client)
    started, finished = sink.events
    assert isinstance(started, LlmCallStarted)
    assert isinstance(finished, LlmCallFinished)
    assert started.request_hash == llm_cache_key(client.requests[0])
    assert (started.agent, started.attempt, started.prompt_sha256) == ("judge", 1, REF.sha256)
    assert started.model.deployment == "model-a"
    assert (finished.input_tokens, finished.output_tokens, finished.cached_input_tokens) == (10, 4, 3)
    assert finished.reasoning_tokens is None
    assert (finished.finish_reason, finished.served_model, finished.cache_hit) == ("stop", "gpt-x", False)
    assert finished.at > started.at


def replace_served(resp: LlmResponse) -> LlmResponse:
    return LlmResponse.model_validate({**resp.model_dump(), "served_model": "gpt-x"})


def test_a_repair_is_a_second_logical_attempt() -> None:
    sink, _ = run(ScriptedLlmClient([response("{}"), response('{"ok": true}')]))
    assert kinds(sink) == [
        "llm.call_started",
        "llm.call_finished",
        "llm.repair_requested",
        "llm.call_started",
        "llm.call_finished",
    ]
    repair = sink.events[2]
    assert isinstance(repair, LlmRepairRequested)
    assert repair.problems == (("ok", "missing"),)
    assert [getattr(e, "attempt", None) for e in sink.events] == [1, 1, 1, 2, 2]


def test_two_invalid_replies_fail_once_after_two_attempts() -> None:
    sink, error = run(ScriptedLlmClient([response("{}"), response("nope")]))
    assert isinstance(error, LlmCallError)
    failed = sink.events[-1]
    assert isinstance(failed, LlmCallFailed)
    assert (failed.error_code, failed.kind, failed.attempts) == ("llm.call_failed", "invalid_output", 2)
    assert kinds(sink).count("llm.call_failed") == 1


@pytest.mark.parametrize(
    ("finish", "kind"),
    [(FinishReason.LENGTH, "truncated"), (FinishReason.CONTENT_FILTER, "content_filtered")],
)
def test_truncation_and_filters_finish_then_fail(finish: FinishReason, kind: str) -> None:
    sink, _ = run(ScriptedLlmClient([response("{", finish=finish)]))
    assert kinds(sink) == ["llm.call_started", "llm.call_finished", "llm.call_failed"]
    failed = sink.events[-1]
    assert isinstance(failed, LlmCallFailed)
    assert failed.kind == kind


def test_a_filtered_prompt_is_an_unmeasured_content_filter_failure() -> None:
    sink, error = run(ScriptedLlmClient([LlmPromptFilteredError(deployment="model-a")]))
    assert isinstance(error, LlmCallError)
    assert error.kind is LlmFailureKind.CONTENT_FILTERED
    assert (error.spend.calls, error.spend.unmeasured_calls, error.spend.cost) == (0, 1, None)
    assert error.spend.usage == Usage.zero()
    assert kinds(sink) == ["llm.call_started", "llm.call_failed"]


def test_a_transport_error_propagates_unchanged_after_one_failure_event() -> None:
    boom = LlmTransportError(deployment="model-a", status=503, attempts=4, reason="unavailable")
    sink = InMemoryEventSink()
    runner = LlmRunner[str, Out](
        ScriptedLlmClient([boom]), spec(), Out, emitter=EventEmitter(sink, stepping_clock())
    )
    with pytest.raises(LlmTransportError) as raised:
        runner.run(Invocation(payload="claim", request=request()))
    assert raised.value is boom
    failed = sink.events[-1]
    assert isinstance(failed, LlmCallFailed)
    assert (failed.error_code, failed.kind, failed.attempts, failed.agent) == ("llm.transport", None, 1, None)


class Rogue(BaseRequestProcessor[str]):
    @override
    def process(self, invocation: Invocation[str]) -> Invocation[str]:
        return replace(invocation, responses=(response(),))


def test_a_failure_before_any_call_reports_zero_attempts() -> None:
    sink = InMemoryEventSink()
    runner = LlmRunner[str, Out](
        ScriptedLlmClient([]),
        spec(),
        Out,
        request_processors=(Rogue(),),
        emitter=EventEmitter(sink, stepping_clock()),
    )
    with pytest.raises(ProcessorContractError):
        runner.run(Invocation(payload="claim", request=request()))
    (failed,) = sink.events
    assert isinstance(failed, LlmCallFailed)
    assert failed.attempts == 0


def test_a_cache_hit_is_visible_on_the_finished_event() -> None:
    cache = InMemoryCache()
    live = CachingLlmClient(ScriptedLlmClient([response()]), cache, CacheMode.READ_WRITE)
    run(live)
    replay = CachingLlmClient(None, cache, CacheMode.READ_ONLY)
    sink, _ = run(replay)
    finished = sink.events[1]
    assert isinstance(finished, LlmCallFinished)
    assert finished.cache_hit


def test_a_lost_cache_race_reports_what_this_run_paid() -> None:
    stored = Usage(input_tokens=10, output_tokens=4)
    billed = Usage(input_tokens=12, output_tokens=6)
    lost = LlmResponse.model_validate(
        {**response(usage=stored).model_dump(), "billed_usage": billed.model_dump()}
    )
    sink, _ = run(ScriptedLlmClient([lost]))
    finished = sink.events[1]
    assert isinstance(finished, LlmCallFinished)
    assert (finished.input_tokens, finished.output_tokens, finished.cache_hit) == (12, 6, False)
