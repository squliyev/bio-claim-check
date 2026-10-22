"""The agent base (ADR 0015, I57): declarations fail at construction, `run` is the one path, stage events."""

from collections.abc import Mapping
from typing import Any, override

import pytest
from tests.support.events import stepping_clock
from tests.support.llm import response, spec

from bio_claim_check.common.models import ValidatedModel
from bio_claim_check.engine.agent.agent_result import AgentResult
from bio_claim_check.engine.agent.base_llm_agent import BaseLlmAgent
from bio_claim_check.engine.agent.errors import AgentDeclarationError
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.in_memory_event_sink import InMemoryEventSink
from bio_claim_check.engine.events.stage_events import StageFailed
from bio_claim_check.engine.llm.errors import LlmCallError
from bio_claim_check.engine.llm.scripted_llm_client import ScriptedLlmClient
from bio_claim_check.engine.prompts.prompt_template import PromptRenderError, PromptTemplate

pytestmark = pytest.mark.unit

PROMPT = PromptTemplate(name="echo", version=1, system="Echo checker.", user="Say $word.")


class Word(ValidatedModel):
    word: str


class EchoLlmAgent(BaseLlmAgent[str, Word]):
    name = "echo"
    prompt = PROMPT
    output = Word

    @override
    def variables(self, payload: str) -> Mapping[str, str]:
        return {"word": payload}


def _client(replies: list[str]) -> ScriptedLlmClient:
    return ScriptedLlmClient([response(r) for r in replies])


def _sink_emitter() -> tuple[InMemoryEventSink, EventEmitter]:
    sink = InMemoryEventSink()
    return sink, EventEmitter(sink, stepping_clock())


def test_run_renders_the_payload_and_merges_call_params_over_the_spec() -> None:
    client = _client(['{"word": "hi"}'])
    result = EchoLlmAgent(client, spec()).run("hi", params={"temperature": 1})
    assert isinstance(result, AgentResult)
    assert result.output == Word(word="hi")
    sent = client.requests[0]
    assert [m.content for m in sent.messages] == ["Echo checker.", "Say hi."]
    assert sent.params["temperature"] == 1
    assert sent.params["nested"] == {"top_p": 1}  # the spec's default survives
    assert sent.prompt == PROMPT.ref()


def test_a_render_failure_is_a_failed_stage_and_no_call() -> None:
    class Wrong(EchoLlmAgent):
        @override
        def variables(self, payload: str) -> Mapping[str, str]:
            return {"other": payload}

    sink, emitter = _sink_emitter()
    client = _client([])
    with pytest.raises(PromptRenderError):
        Wrong(client, spec(), emitter=emitter).run("hi")
    assert client.requests == []
    assert [e.type for e in sink.events] == ["stage.started", "stage.failed"]
    failed = sink.events[-1]
    assert isinstance(failed, StageFailed)
    assert failed.error_code == "prompts.render"


def test_a_call_failure_is_reported_once_by_the_runner_and_once_by_the_stage() -> None:
    sink, emitter = _sink_emitter()
    client = _client(["not json", "still not json"])
    with pytest.raises(LlmCallError):
        EchoLlmAgent(client, spec(), emitter=emitter).run("hi")
    types = [e.type for e in sink.events]
    assert types[0] == "stage.started"
    assert types[-2:] == ["llm.call_failed", "stage.failed"]
    assert types.count("llm.call_failed") == 1


def test_without_an_emitter_the_agent_is_silent_and_still_works() -> None:
    assert EchoLlmAgent(_client(['{"word": "x"}']), spec()).run("x").output.word == "x"


def _declare(**attrs: object) -> type[Any]:
    body: dict[str, object] = {"name": "echo", "prompt": PROMPT, "output": Word} | attrs
    body = {k: v for k, v in body.items() if v is not _MISSING}
    body["variables"] = lambda self, payload: {}  # pyright: ignore[reportUnknownLambdaType]  # dynamic class
    return type("Declared", (BaseLlmAgent,), body)


_MISSING = object()


def _run_override(self: object, payload: object) -> None:
    return None


DECLARATION_ERRORS: list[tuple[dict[str, object], str]] = [
    ({"name": _MISSING}, "name must match"),
    ({"name": "Echo"}, "name must match"),
    ({"name": "echo-agent"}, "name must match"),
    ({"name": ""}, "name must match"),
    ({"prompt": "Say hi."}, "prompt must be a PromptTemplate"),
    ({"prompt": _MISSING}, "prompt must be a PromptTemplate"),
    ({"output": dict}, "output must be a pydantic model"),
    ({"output": Word(word="x")}, "output must be a pydantic model"),
    ({"run": _run_override}, "overrides run"),
]


@pytest.mark.parametrize(("attrs", "message"), DECLARATION_ERRORS)
def test_a_misdeclared_agent_fails_at_construction(attrs: dict[str, object], message: str) -> None:
    cls = _declare(**attrs)  # class creation itself never fails: no import-time hooks (I28)
    with pytest.raises(AgentDeclarationError, match=message):
        cls(_client([]), spec())


def test_overriding_run_deeper_in_the_hierarchy_is_also_caught() -> None:
    class Middle(EchoLlmAgent):
        pass

    class Sneaky(Middle):
        @override
        def run(self, *args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportIncompatibleMethodOverride]  # the bug under test
            return None

    with pytest.raises(AgentDeclarationError, match="overrides run"):
        Sneaky(_client([]), spec())
