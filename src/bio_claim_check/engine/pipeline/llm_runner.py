"""[RING:engine/pipeline] The one path every structured LLM call takes, in a fixed, readable order.

Why: repair loops, truncation and content filters are where structured-output code usually hides
failures or double-counts money. The order here is the whole contract (ADR 0012):
1. request processors (once);
2. the response schema, derived from the output type (callers cannot pass a mismatching one);
3. the client call; 4. spend recorded at once (before anything can fail);
5. a content filter or truncation fails at once, never repaired (it would happen again);
6. validation; only a validation error (incl. invalid JSON) earns ONE repair turn;
7. typed response processors.
Every failure is an `LlmCallError` carrying the spend of all its attempts. Any other exception (client,
cache, processor) propagates unchanged: no blind except.
Processors may not touch what the runner owns: a request processor may reshape messages but not the model,
responses or spend; a response processor may change only the payload. A violation raises
`ProcessorContractError`, because it would send the call to the wrong model or hide what was paid.
The repair turn lists only field locations and error types, never validator messages, which can echo
model-controlled values into a user-role message.
Must not: retry transport errors (that is the backend's job, S09), or repair more than once.
"""

from collections.abc import Sequence
from dataclasses import replace

from pydantic import BaseModel, ValidationError

from bio_claim_check.engine.llm.base_llm_client import BaseLlmClient
from bio_claim_check.engine.llm.errors import LlmCallError, LlmFailureKind
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


class ProcessorContractError(RuntimeError):
    """A processor changed a field the runner owns (model identity, responses, spend, or the request)."""


def _problems(error: ValidationError) -> tuple[tuple[str, str], ...]:
    return tuple((".".join(str(part) for part in e["loc"]) or "<root>", e["type"]) for e in error.errors())


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
    ) -> None:
        self._client = client
        self._spec = spec
        self._output = output
        self._request = tuple(request_processors)
        self._response = tuple(response_processors)

    def run(self, invocation: Invocation[P]) -> tuple[T, Invocation[P]]:
        if invocation.request.model != self._spec.identity():
            raise ValueError(
                f"request is for {invocation.request.model}, runner is for {self._spec.identity()}"
            )
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
        inv = replace(inv, request=inv.request.with_schema(self._output.__name__, schema))
        for attempt in range(1, MAX_ATTEMPTS + 1):
            response = self._client.complete(inv.request)
            inv = self._record(inv, response)
            if response.finish_reason is FinishReason.CONTENT_FILTER:
                raise self._error(LlmFailureKind.CONTENT_FILTERED, inv, attempt)
            if response.finish_reason is FinishReason.LENGTH:
                raise self._error(LlmFailureKind.TRUNCATED, inv, attempt)
            try:
                output = self._output.model_validate_json(response.text)
            except ValidationError as error:
                problems = _problems(error)
                if attempt == MAX_ATTEMPTS:
                    raise self._error(
                        LlmFailureKind.INVALID_OUTPUT,
                        inv,
                        attempt,
                        problems,
                    ) from error
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
