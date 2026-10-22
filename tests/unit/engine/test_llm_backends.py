"""Both provider backends over a mock transport: fixtures, retries, typed failures, no leaked bodies (I55)."""

import logging
from typing import Any

import httpx2
import pytest
from tests.support.events import stepping_clock
from tests.support.llm_fixtures import (
    PROVIDERS,
    LlmFixture,
    ProviderDir,
    anthropic_sdk,
    backend,
    fixture_paths,
    load_fixture,
    load_fixtures,
    openai_sdk,
    replay,
)

from bio_claim_check.common.errors import BccError
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.in_memory_event_sink import InMemoryEventSink
from bio_claim_check.engine.events.llm_events import LlmRetryScheduled
from bio_claim_check.engine.llm.anthropic_llm_client import AnthropicLlmClient
from bio_claim_check.engine.llm.errors import (
    LlmPromptFilteredError,
    LlmProviderError,
    LlmTransportError,
    LlmUnexpectedResponseError,
)
from bio_claim_check.engine.llm.openai_llm_client import OpenAiLlmClient

pytestmark = pytest.mark.unit

SENTINEL = "SENTINEL-abstract-text-must-not-leak"


def _fixture(name: str) -> LlmFixture:
    return next(f for f in load_fixtures() if f.name == name)


@pytest.mark.parametrize("path", fixture_paths(), ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_every_fixture_replays_to_its_expected_result(path: Any) -> None:
    fixture = load_fixture(path)
    sleeps: list[float] = []
    client, transport = replay(fixture, sleeps=sleeps)
    if fixture.expected is not None:
        assert client.complete(fixture.request) == fixture.expected
    else:
        with pytest.raises(BccError) as caught:
            client.complete(fixture.request)
        assert caught.value.code == fixture.expected_error
    assert transport.pending == [], "every recorded exchange is used"
    assert len(sleeps) == len(fixture.exchanges) - 1


def test_a_throttled_call_waits_for_the_provider_hint() -> None:
    sleeps: list[float] = []
    client, _ = replay(_fixture("foundry_openai/throttled_then_ok"), sleeps=sleeps)
    client.complete(_fixture("foundry_openai/throttled_then_ok").request)
    assert sleeps == [2.0]


def _always(status: int, body: object, headers: dict[str, str] | None = None) -> httpx2.MockTransport:
    return httpx2.MockTransport(lambda _r: httpx2.Response(status, json=body, headers=headers or {}))


def _raising(error: Exception) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error

    return httpx2.MockTransport(handler)


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("status", [401, 403, 404, 422])
def test_a_rejection_is_not_retried_and_never_carries_the_body(
    provider: ProviderDir, status: int, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    sleeps: list[float] = []
    body = {"error": {"code": "Denied", "message": SENTINEL}}
    client = backend(provider, _always(status, body), sleeps=sleeps)
    with pytest.raises(LlmProviderError) as caught:
        client.complete(load_fixtures(provider)[0].request)
    assert (caught.value.status, caught.value.provider_code) == (status, "Denied")
    assert sleeps == []
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert SENTINEL not in str(caught.value)
    assert SENTINEL not in caplog.text


@pytest.mark.parametrize("provider", PROVIDERS)
def test_connection_failures_are_retried_on_the_fixed_schedule_then_fail(provider: ProviderDir) -> None:
    sleeps: list[float] = []
    client = backend(provider, _raising(httpx2.ConnectError("refused")), sleeps=sleeps)
    with pytest.raises(LlmTransportError) as caught:
        client.complete(load_fixtures(provider)[0].request)
    assert (caught.value.status, caught.value.attempts) == (None, 4)
    assert sleeps == [1.0, 2.0, 4.0]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_read_timeout_is_never_retried(provider: ProviderDir) -> None:
    sleeps: list[float] = []
    client = backend(provider, _raising(httpx2.ReadTimeout("slow")), sleeps=sleeps)
    with pytest.raises(LlmTransportError, match="may have been billed") as caught:
        client.complete(load_fixtures(provider)[0].request)
    assert caught.value.attempts == 1
    assert sleeps == []


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize(
    "error",
    [httpx2.RemoteProtocolError("disconnected"), httpx2.ReadError("reset"), httpx2.WriteError("broken")],
    ids=type,
)
def test_a_connection_lost_after_sending_is_never_retried(provider: ProviderDir, error: Exception) -> None:
    sleeps: list[float] = []
    client = backend(provider, _raising(error), sleeps=sleeps)
    with pytest.raises(LlmTransportError, match="may have been billed") as caught:
        client.complete(load_fixtures(provider)[0].request)
    assert caught.value.attempts == 1
    assert sleeps == []


@pytest.mark.parametrize("provider", PROVIDERS)
def test_every_retry_emits_one_event(provider: ProviderDir) -> None:
    sink = InMemoryEventSink()
    sleeps: list[float] = []
    transport = _always(503, {"error": {"code": "busy"}}, {"retry-after-ms": "250", "x-request-id": SENTINEL})
    client = backend(provider, transport, sleeps=sleeps, emitter=EventEmitter(sink, stepping_clock()))
    request = load_fixtures(provider)[0].request
    with pytest.raises(LlmTransportError):
        client.complete(request)
    events = [e for e in sink.events if isinstance(e, LlmRetryScheduled)]
    assert [(e.transport_attempt, e.status, e.delay_s) for e in events] == [(i, 503, 0.25) for i in (1, 2, 3)]
    assert {e.model.deployment for e in events} == {request.model.deployment}
    assert sleeps == [0.25] * 3
    assert SENTINEL not in repr(sink.events)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_prompt_filter_is_its_own_error(provider: ProviderDir) -> None:
    body = {"error": {"code": "content_filter", "message": SENTINEL}}
    client = backend(provider, _always(400, body))
    with pytest.raises(LlmPromptFilteredError) as caught:
        client.complete(load_fixtures(provider)[0].request)
    assert SENTINEL not in str(caught.value)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_body_that_is_not_an_object_is_unexpected(provider: ProviderDir) -> None:
    client = backend(provider, _always(200, ["not", "an", "object"]))
    with pytest.raises(LlmUnexpectedResponseError):
        client.complete(load_fixtures(provider)[0].request)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_body_that_is_not_json_is_unexpected_and_never_carries_the_body(provider: ProviderDir) -> None:
    transport = httpx2.MockTransport(
        lambda _r: httpx2.Response(
            200, content=f'{{"trunc {SENTINEL}'.encode(), headers={"content-type": "application/json"}
        )
    )
    with pytest.raises(LlmUnexpectedResponseError) as caught:
        backend(provider, transport).complete(load_fixtures(provider)[0].request)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    assert SENTINEL not in str(caught.value)


def test_sdk_retries_must_be_off() -> None:
    transport = _always(200, {})
    with pytest.raises(ValueError, match="max_retries=0"):
        OpenAiLlmClient(openai_sdk(transport, max_retries=2), sleep=lambda _s: None)
    with pytest.raises(ValueError, match="max_retries=0"):
        AnthropicLlmClient(anthropic_sdk(transport, max_retries=1), sleep=lambda _s: None)
