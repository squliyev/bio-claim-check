"""[RING:engine/agent] The one base every LLM agent extends: declare, then run through `LlmRunner`.

Why: without it each LLM feature would re-assemble prompt render → `request_for` → `Invocation` →
`LlmRunner`, and each copy could forget the `PromptRef`, the agent label on its events or the stage
events. A subclass declares `name`, `prompt` and `output` and writes `variables(payload)`; `run` is the
only path from a payload to a request, and it is final. Declarations are checked when the first agent is
built (not at import: no import-time hooks, I28). The agent is a stateless service object: built once,
it keeps nothing between calls; per-call state travels in the `Invocation`.
Must not: re-implement the runner's attempt/repair/spend logic, catch non-`BccError` exceptions, emit
message text or payloads (events carry ids and codes only, ADR 0016), or hold domain prompt text.
"""

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import final

from pydantic import BaseModel, JsonValue

from bio_claim_check.common.errors import BccError
from bio_claim_check.engine.agent.agent_result import AgentResult
from bio_claim_check.engine.agent.errors import AgentDeclarationError
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.stage_events import StageFailed, StageFinished, StageStarted
from bio_claim_check.engine.llm.base_llm_client import BaseLlmClient
from bio_claim_check.engine.llm.messages import request_for
from bio_claim_check.engine.llm.model_spec import ModelSpec
from bio_claim_check.engine.pipeline.base_request_processor import BaseRequestProcessor
from bio_claim_check.engine.pipeline.base_response_processor import BaseResponseProcessor
from bio_claim_check.engine.pipeline.invocation import Invocation
from bio_claim_check.engine.pipeline.llm_runner import LlmRunner
from bio_claim_check.engine.prompts.prompt_template import PromptTemplate, render

AGENT_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class BaseLlmAgent[P, T: BaseModel](ABC):
    """[EXTENSION POINT] Implemented in any features/engine package as `<what>_llm_agent.py`.

    Subclasses set the class attributes `name` (a stable id, `^[a-z][a-z0-9_]*$`), `prompt` and
    `output`, and implement `variables`.
    """

    name: str
    prompt: PromptTemplate
    output: type[T]

    def __init__(
        self,
        client: BaseLlmClient,
        spec: ModelSpec,
        *,
        emitter: EventEmitter | None = None,
        request_processors: Sequence[BaseRequestProcessor[P]] = (),
        response_processors: Sequence[BaseResponseProcessor[P, T]] = (),
    ) -> None:
        _check_declaration(type(self))
        self._spec = spec
        self._emitter = emitter
        self._runner = LlmRunner(
            client,
            spec,
            self.output,
            request_processors=request_processors,
            response_processors=response_processors,
            emitter=emitter,
            agent=self.name,
        )

    @abstractmethod
    def variables(self, payload: P) -> Mapping[str, str]:
        """The template variables for `payload`: the only thing a subclass writes."""

    @final
    def run(
        self, payload: P, *, repeat_idx: int = 0, params: Mapping[str, JsonValue] | None = None
    ) -> AgentResult[P, T]:
        """Render, request (with the prompt's `PromptRef`), run; stage events around the whole call."""
        emitter, stage = self._emitter, self.name
        if emitter is not None:
            emitter.emit(lambda at: StageStarted(at=at, stage=stage))
        try:
            messages = render(self.prompt, self.variables(payload))
            request = request_for(
                self._spec, messages, params=params, repeat_idx=repeat_idx, prompt=self.prompt.ref()
            )
            output, invocation = self._runner.run(Invocation(payload=payload, request=request))
        except BccError as error:
            if emitter is not None:
                code = error.code
                emitter.emit(lambda at: StageFailed(at=at, stage=stage, error_code=code))
            raise
        if emitter is not None:
            emitter.emit(lambda at: StageFinished(at=at, stage=stage))
        return AgentResult(agent=stage, output=output, invocation=invocation)


def _check_declaration(cls: type) -> None:
    where = cls.__qualname__
    name: object = getattr(cls, "name", None)
    if not isinstance(name, str) or not AGENT_NAME.fullmatch(name):
        raise AgentDeclarationError(f"{where}.name must match {AGENT_NAME.pattern}, got {name!r}")
    if not isinstance(getattr(cls, "prompt", None), PromptTemplate):
        raise AgentDeclarationError(f"{where}.prompt must be a PromptTemplate")
    output: object = getattr(cls, "output", None)
    if not (isinstance(output, type) and issubclass(output, BaseModel)):
        raise AgentDeclarationError(f"{where}.output must be a pydantic model class")
    below_base = cls.__mro__[: cls.__mro__.index(BaseLlmAgent)]
    if any("run" in vars(c) for c in below_base):
        raise AgentDeclarationError(f"{where} overrides run; agents write variables() only")
