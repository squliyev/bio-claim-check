"""Every LLM agent keeps the agent-base contract (I57, ADR 0015).

A new agent adds itself to `IMPLEMENTATIONS` with one `AgentCase`: a payload and a reply its output model
accepts. The suite then proves the declaration is valid, the request carries the prompt's `PromptRef`,
every event is labelled with the agent, the stage is wrapped in events, and the agent keeps no state.
"""

from dataclasses import dataclass
from typing import Any

import pytest

from bio_claim_check.app.container import default_rulepack
from bio_claim_check.engine.agent.base_llm_agent import AGENT_NAME, BaseLlmAgent
from bio_claim_check.engine.agent.ping_llm_agent import PingLlmAgent
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.in_memory_event_sink import InMemoryEventSink
from bio_claim_check.engine.llm.scripted_llm_client import ScriptedLlmClient
from bio_claim_check.features.answer.answer_models import AnswerPayload
from bio_claim_check.features.answer.over_eager_answer_llm_agent import OverEagerAnswerLlmAgent
from bio_claim_check.features.answer.strict_answer_llm_agent import StrictAnswerLlmAgent
from bio_claim_check.features.retrieval.in_memory_literature_source import FAKE_CORPUS
from bio_claim_check.features.verify.verify_llm_agent import VerifyLlmAgent
from bio_claim_check.features.verify.verify_models import VerifyPayload
from tests.support.events import stepping_clock
from tests.support.llm import response, spec

pytestmark = pytest.mark.contract

type AnyAgent = BaseLlmAgent[Any, Any]

IMPLEMENTATIONS: tuple[type[AnyAgent], ...] = (
    PingLlmAgent,
    StrictAnswerLlmAgent,
    OverEagerAnswerLlmAgent,
    VerifyLlmAgent,
)


@dataclass(frozen=True)
class AgentCase:
    payload: object
    reply: str  # JSON the agent's output model accepts


ANSWER = AgentCase(
    payload=AnswerPayload(question="Does OS-912 work?", papers=FAKE_CORPUS),
    reply='{"claims": [{"text": "OS-912 reduced plaque in mice.", "cites": ["FAKE:1"]}]}',
)
CASES: dict[type[AnyAgent], AgentCase] = {
    PingLlmAgent: AgentCase(payload=None, reply='{"ok": true}'),
    StrictAnswerLlmAgent: ANSWER,
    OverEagerAnswerLlmAgent: ANSWER,
    VerifyLlmAgent: AgentCase(
        payload=VerifyPayload(
            claim="OS-912 reduced plaque in mice.",
            title=FAKE_CORPUS[0].title,
            abstract=FAKE_CORPUS[0].abstract,
            rules=default_rulepack(),
        ),
        reply='{"label": "not_in_source", "overstated_reason": null, "evidence": null, "reason": "Absent."}',
    ),
}


@pytest.fixture(params=IMPLEMENTATIONS, ids=lambda c: c.__name__)
def agent_class(request: pytest.FixtureRequest) -> type[AnyAgent]:
    return request.param


def _agent(cls: type[AnyAgent], replies: int, sink: InMemoryEventSink | None = None) -> AnyAgent:
    client = ScriptedLlmClient([response(CASES[cls].reply)] * replies)
    emitter = None if sink is None else EventEmitter(sink, stepping_clock())
    return cls(client, spec(), emitter=emitter)


def test_every_agent_has_a_case() -> None:
    assert set(CASES) == set(IMPLEMENTATIONS)


def test_the_declaration_is_valid(agent_class: type[AnyAgent]) -> None:
    assert AGENT_NAME.fullmatch(agent_class.name)
    _agent(agent_class, 0)  # construction checks the declaration


def test_run_returns_the_validated_output_labelled_with_the_agent(agent_class: type[AnyAgent]) -> None:
    agent = _agent(agent_class, 1)
    result = agent.run(CASES[agent_class].payload)
    assert result.agent == agent_class.name
    assert isinstance(result.output, agent.output)
    assert result.invocation.payload == CASES[agent_class].payload


def test_the_request_carries_the_prompt_ref_and_the_spec_identity(agent_class: type[AnyAgent]) -> None:
    result = _agent(agent_class, 1).run(CASES[agent_class].payload, repeat_idx=2)
    assert result.invocation.request.prompt == agent_class.prompt.ref()
    assert result.invocation.request.model == spec().identity()
    assert result.invocation.request.repeat_idx == 2


def test_the_stage_is_wrapped_and_every_llm_event_names_the_agent(agent_class: type[AnyAgent]) -> None:
    sink = InMemoryEventSink()
    _agent(agent_class, 1, sink).run(CASES[agent_class].payload)
    types = [e.type for e in sink.events]
    assert types[0] == "stage.started"
    assert types[-1] == "stage.finished"
    assert {getattr(e, "stage", agent_class.name) for e in sink.events} == {agent_class.name}
    llm = [e for e in sink.events if e.type.startswith("llm.")]
    assert llm
    assert {getattr(e, "agent", None) for e in llm} == {agent_class.name}


def test_the_agent_keeps_no_state_between_runs(agent_class: type[AnyAgent]) -> None:
    agent = _agent(agent_class, 2)
    before = dict(vars(agent))
    first = agent.run(CASES[agent_class].payload)
    second = agent.run(CASES[agent_class].payload, repeat_idx=1)
    assert {k: id(v) for k, v in vars(agent).items()} == {k: id(v) for k, v in before.items()}
    assert len(first.invocation.responses) == len(second.invocation.responses) == 1
    assert first.invocation.request.repeat_idx == 0
