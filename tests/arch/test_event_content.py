"""Events never carry content (I59, ADR 0016).

A sentinel is planted in the prompt, the payload and every model reply, and the whole stack runs: agent,
runner, a real backend and its SDK over a mock transport, for both providers. The run covers a transport
retry, a repair round, success, and a failed call, so every event type is emitted. No serialised event may
contain a sentinel, the endpoint host or the key.
"""

import contextlib
import copy
import json
from collections.abc import Callable, Mapping
from typing import Any, override

import httpx2
import pytest

from bio_claim_check.app.models import model_catalog
from bio_claim_check.common.models import ValidatedModel
from bio_claim_check.engine.agent.base_llm_agent import BaseLlmAgent
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.in_memory_event_sink import InMemoryEventSink
from bio_claim_check.engine.events.pipeline_event import PipelineEvent
from bio_claim_check.engine.llm.errors import LlmCallError
from bio_claim_check.engine.prompts.prompt_template import PromptTemplate
from tests.support.events import stepping_clock
from tests.support.llm_fixtures import (
    API_KEY,
    LLM_FIXTURES,
    SCRUBBED_HOST,
    ProviderDir,
    backend,
    load_fixture,
)

pytestmark = pytest.mark.arch

IN_PROMPT = "PROMPTSENTINEL"
IN_PAYLOAD = "PAYLOADSENTINEL"
IN_OUTPUT = "OUTPUTSENTINEL"
FORBIDDEN = (IN_PROMPT, IN_PAYLOAD, IN_OUTPUT, SCRUBBED_HOST, API_KEY)
DEPLOYMENTS: dict[ProviderDir, str] = {
    "foundry_openai": "gpt-6.1-sol",
    "foundry_anthropic": "claude-opus-4-8",
}


class Word(ValidatedModel):
    word: str


class LeakyLlmAgent(BaseLlmAgent[str, Word]):
    name = "leaky"
    prompt = PromptTemplate(name="leaky", version=1, system=f"Secret {IN_PROMPT}.", user="Echo $text.")
    output = Word

    @override
    def variables(self, payload: str) -> Mapping[str, str]:
        return {"text": payload}


def _reply(provider: ProviderDir, answer: dict[str, Any]) -> dict[str, Any]:
    """The recorded `ok` body with its answer replaced, so the SDK and codec see a real response shape."""
    body = copy.deepcopy(load_fixture(LLM_FIXTURES / provider / "ok.json").exchanges[-1].response)
    if provider == "foundry_openai":
        for item in body["output"]:
            for part in item.get("content") or ():
                if part["type"] == "output_text":
                    part["text"] = json.dumps(answer)
    else:
        for block in body["content"]:
            if block["type"] == "tool_use":
                block["name"] = Word.__name__
                block["input"] = answer
    return body


def _ok(provider: ProviderDir, answer: dict[str, Any]) -> Callable[[], httpx2.Response]:
    return lambda: httpx2.Response(200, json=_reply(provider, answer))


def _transport(provider: ProviderDir, answers: list[dict[str, Any]]) -> httpx2.MockTransport:
    """A 429 first (a transport retry), then one reply per answer."""
    queue: list[Callable[[], httpx2.Response]] = [
        lambda: httpx2.Response(429, headers={"retry-after": "0"}, json={"error": {"message": IN_OUTPUT}})
    ]
    queue += [_ok(provider, a) for a in answers]
    return httpx2.MockTransport(lambda _: queue.pop(0)())


def _run(provider: ProviderDir, answers: list[dict[str, Any]]) -> list[PipelineEvent]:
    sink = InMemoryEventSink()
    emitter = EventEmitter(sink, stepping_clock())
    client = backend(provider, _transport(provider, answers), emitter=emitter)
    agent = LeakyLlmAgent(client, model_catalog().lookup(DEPLOYMENTS[provider]), emitter=emitter)
    with contextlib.suppress(LlmCallError):  # the failed run is part of the scenario
        agent.run(f"the {IN_PAYLOAD}")
    return list(sink.events)


BAD = {"word": 7, IN_OUTPUT: IN_OUTPUT}  # a model-invented key must not reach a validation location
GOOD = {"word": IN_OUTPUT}


@pytest.mark.parametrize("provider", list(DEPLOYMENTS))
@pytest.mark.parametrize(
    ("answers", "outcome"), [([BAD, GOOD], "stage.finished"), ([BAD, BAD], "stage.failed")]
)
def test_no_event_carries_prompt_payload_output_host_or_key(
    provider: ProviderDir, answers: list[dict[str, Any]], outcome: str
) -> None:
    events = _run(provider, answers)
    types = [e.type for e in events]
    assert {"llm.retry_scheduled", "llm.repair_requested", "llm.call_finished", outcome} <= set(types)
    for event in events:
        dumped = event.model_dump_json()
        for forbidden in FORBIDDEN:
            assert forbidden not in dumped, f"{event.type} carries {forbidden}"
