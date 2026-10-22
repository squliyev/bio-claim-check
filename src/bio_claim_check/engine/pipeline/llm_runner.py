"""[RING:engine/pipeline] The one path every structured LLM call takes, in a fixed, readable order.

Why: repair loops, truncation and content filters are where structured-output code usually hides
failures or double-counts money. The order here is the whole contract (ADR 0012):
1. request processors (once);
2. the response schema, derived from the output type (callers cannot pass a mismatching one);
3. the client call; 4. spend recorded at once (before anything can fail);
5. a content filter or truncation fails at once, never repaired (it would happen again);
6. validation; only a validation error (incl. invalid JSON) earns ONE repair turn;
7. typed response processors.
Every failure is an `LlmCallError` carrying the spend of all its attempts. A prompt rejected by the
provider's filter (`LlmPromptFilteredError`) is recorded as an unmeasured call and fails as
`content_filtered`. Any other exception (client, cache, processor) propagates unchanged: no blind except.
Events (ADR 0016, I60), when an emitter is given: each logical attempt emits `LlmCallStarted` and then
`LlmCallFinished` once a response exists; a repair emits `LlmRepairRequested`; a typed (`BccError`)
failure emits one `LlmCallFailed` before it propagates. Events carry no text (I59).
Processors may not touch what the runner owns: a request processor may reshape messages but not the model,
responses or spend; a response processor may change only the payload. A violation raises
`ProcessorContractError`, because it would send the call to the wrong model or hide what was paid.
The repair turn lists only field locations and error types, never validator messages, which can echo
model-controlled values into a user-role message.
Must not: retry transport errors (that is the backend's job, S09), or repair more than once.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime

from pydantic import BaseModel, JsonValue, ValidationError

from bio_claim_check.common.errors import BccError
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.llm_events import (
    LlmCallFailed,
    LlmCallFinished,
    LlmCallStarted,
    LlmRepairRequested,
)
from bio_claim_check.engine.events.pipeline_event import PipelineEvent
from bio_claim_check.engine.llm.base_llm_client import BaseLlmClient
from bio_claim_check.engine.llm.errors import LlmCallError, LlmFailureKind, LlmPromptFilteredError
from bio_claim_check.engine.llm.event_refs import model_ref
from bio_claim_check.engine.llm.llm_cache_key import llm_cache_key
from bio_claim_check.engine.llm.messages import FinishReason, LlmRequest, LlmResponse, Message
from bio_claim_check.engine.llm.model_spec import ModelSpec
from bio_claim_check.engine.pipeline.base_request_processor import BaseRequestProcessor
from bio_claim_check.engine.pipeline.base_response_processor import BaseResponseProcessor
from bio_claim_check.engine.pipeline.invocation import Invocation

MAX_ATTEMPTS = 2
REPAIR_INSTRUCTION = (
    "Your previous reply did not match the required JSON schema. Problems: {problems}. "
    "Reply again with only the corrected JSON object."
)
EMPTY_REPLY = "(empty reply)"


class ProcessorContractError(BccError, RuntimeError):
    """A processor changed a field the runner owns (model identity, responses, spend, or the request)."""

    code = "llm.processor_contract"


UNDECLARED = "<undeclared>"


def declared_names(schema: JsonValue) -> frozenset[str]:
    """Every property name the output schema declares, at any depth."""
    names: set[str] = set()
    if isinstance(schema, list):
        for item in schema:
            names |= declared_names(item)
    elif isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                names.update(value)
            names |= declared_names(value)
    return frozenset(names)


def _problems(error: ValidationError, declared: frozenset[str]) -> tuple[tuple[str, str], ...]:
    """(location, error type) pairs. A segment the schema does not declare (a key the model invented, a
    dict key) is model output, so it becomes `<undeclared>`: problems reach events and error text (I59)."""

    def segment(part: str | int) -> str:
        return str(part) if isinstance(part, int) or part in declared else UNDECLARED

    return tuple((".".join(segment(p) for p in e["loc"]) or "<root>", e["type"]) for e in error.errors())


class LlmRunner[P, T: BaseModel]:
    """Runs invocations for one model spec and one output type; the processor order is the caller's."""

    def __init__(
        self,
        client: BaseLlmClient,
        spec: ModelSpec,
        output: type[T],
        *,
        request_processors: Sequence[BaseRequestProcessor[P]] = (),
        response_processors: Sequence[BaseResponseProcessor[P, T]] = (),
        emitter: EventEmitter | None = None,
        agent: str | None = None,
    ) -> None:
        self._client = client
        self._spec = spec
        self._output = output
        self._request = tuple(request_processors)
        self._response = tuple(response_processors)
        self._emitter = emitter
        self._agent = agent
        self._model = model_ref(spec.identity())

    def run(self, invocation: Invocation[P]) -> tuple[T, Invocation[P]]:
        if invocation.request.model != self._spec.identity():
            raise ValueError(
                f"request is for {invocation.request.model}, runner is for {self._spec.identity()}"
            )
        attempts = [0]  # the logical attempt reached, for the failure event
        try:
            return self._run(invocation, attempts)
        except BccError as error:
            self._failed(error, attempts[0])
            raise

    def _run(self, invocation: Invocation[P], attempts: list[int]) -> tuple[T, Invocation[P]]:
        inv = invocation
        for processor in self._request:
            before = inv
            inv = processor.process(inv)
            if (inv.request.model, inv.responses, inv.spend) != (
                before.request.model,
                before.responses,
                before.spend,
            ):
                raise ProcessorContractError(
                    f"{type(processor).__name__} changed the model, responses or spend"
                )
        schema = self._output.model_json_schema(mode="validation")
        declared = declared_names(schema)
        inv = replace(inv, request=inv.request.with_schema(self._output.__name__, schema))
        for attempt in range(1, MAX_ATTEMPTS + 1):
            attempts[0] = attempt
            self._started(inv.request, attempt)
            try:
                response = self._client.complete(inv.request)
            except LlmPromptFilteredError as error:
                inv = replace(inv, spend=inv.spend.record_unmeasured())
                raise self._error(LlmFailureKind.CONTENT_FILTERED, inv, attempt) from error
            inv = self._record(inv, response)
            self._finished(response, attempt)
            if response.finish_reason is FinishReason.CONTENT_FILTER:
                raise self._error(LlmFailureKind.CONTENT_FILTERED, inv, attempt)
            if response.finish_reason is FinishReason.LENGTH:
                raise self._error(LlmFailureKind.TRUNCATED, inv, attempt)
            try:
                output = self._output.model_validate_json(response.text)
            except ValidationError as error:
                problems = _problems(error, declared)
                if attempt == MAX_ATTEMPTS:
                    raise self._error(
                        LlmFailureKind.INVALID_OUTPUT,
                        inv,
                        attempt,
                        problems,
                    ) from error
                self._repair_requested(attempt, problems)
                inv = replace(inv, request=self._repair_request(inv, response, problems))
                continue
            for processor in self._response:
                before = inv
                inv = processor.process(inv, output)
                if (inv.request, inv.responses, inv.spend) != (
                    before.request,
                    before.responses,
                    before.spend,
                ):
                    raise ProcessorContractError(
                        f"{type(processor).__name__} changed the request, responses or spend"
                    )
            return output, inv
        raise AssertionError("unreachable: the last attempt returns or raises")  # pragma: no cover

    def _emit(self, build: Callable[[datetime], PipelineEvent]) -> None:
        if self._emitter is not None:
            self._emitter.emit(build)

    def _started(self, request: LlmRequest, attempt: int) -> None:
        self._emit(
            lambda at: LlmCallStarted(
                at=at,
                agent=self._agent,
                model=self._model,
                attempt=attempt,
                repeat_idx=request.repeat_idx,
                request_hash=llm_cache_key(request),
                prompt_sha256=None if request.prompt is None else request.prompt.sha256,
            )
        )

    def _finished(self, response: LlmResponse, attempt: int) -> None:
        usage = response.usage
        self._emit(
            lambda at: LlmCallFinished(
                at=at,
                agent=self._agent,
                model=self._model,
                attempt=attempt,
                finish_reason=response.finish_reason.value,
                cache_hit=response.cache_hit,
                served_model=response.served_model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                reasoning_tokens=usage.reasoning_tokens,
                cached_input_tokens=usage.cached_input_tokens,
            )
        )

    def _repair_requested(self, attempt: int, problems: tuple[tuple[str, str], ...]) -> None:
        self._emit(
            lambda at: LlmRepairRequested(
                at=at, agent=self._agent, model=self._model, attempt=attempt, problems=problems
            )
        )

    def _failed(self, error: BccError, attempts: int) -> None:
        kind = error.kind.value if isinstance(error, LlmCallError) else None
        self._emit(
            lambda at: LlmCallFailed(
                at=at,
                agent=self._agent,
                model=self._model,
                error_code=error.code,
                kind=kind,
                attempts=attempts,
            )
        )

    def _record(self, inv: Invocation[P], response: LlmResponse) -> Invocation[P]:
        spend = inv.spend.record(paid=response.paid_usage, usage=response.usage, price=self._spec.price)
        return replace(inv, responses=(*inv.responses, response), spend=spend)

    @staticmethod
    def _repair_request(
        inv: Invocation[P], response: LlmResponse, problems: tuple[tuple[str, str], ...]
    ) -> LlmRequest:
        """The same request plus the model's reply and one engine-owned correction turn."""
        listed = "; ".join(f"{loc} [{kind}]" for loc, kind in problems)
        reply = Message(role="assistant", content=response.text if response.text.strip() else EMPTY_REPLY)
        fix = Message(role="user", content=REPAIR_INSTRUCTION.format(problems=listed))
        return inv.request.with_messages((*inv.request.messages, reply, fix))

    def _error(
        self,
        kind: LlmFailureKind,
        inv: Invocation[P],
        attempts: int,
        validation: tuple[tuple[str, str], ...] = (),
    ) -> LlmCallError:
        return LlmCallError(
            kind, deployment=self._spec.deployment, attempts=attempts, spend=inv.spend, validation=validation
        )
