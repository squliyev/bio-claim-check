"""[RING:engine/llm] Everything the backend knows about the Responses API, as pure dict ↔ model mapping.

Why: provider knowledge in one place that is unit-tested without the SDK or a network (D1). Requests are
stateless and keep nothing at the provider: `store=false`, no `previous_response_id`, no item ids, no
`include`, so reasoning is never sent back or kept (I54). Structured output is a strict `json_schema`,
pre-checked here so an incompatible schema fails at our boundary with its path, not as a provider 400
(D5). Responses decode fail-closed: a refusal content part or an `incomplete` content filter is
CONTENT_FILTER, a token cap is LENGTH, and any state, item or part we do not know raises
`llm.unexpected_response` rather than becoming STOP (I53). Usage is normalised to the engine's
contract: cached ⊆ input, reasoning ⊆ output, unreported reasoning is None (I51, I52).
Must not: import the SDK, perform I/O, or carry a raw value into an error.

Pure logic: makes no provider call. (It is LLM vocabulary, so it does not carry the
ADR 0003 deterministic marker.)
"""

from collections.abc import Mapping

from pydantic import JsonValue

from bio_claim_check.engine.llm.codec_support import (
    count,
    obj,
    optional_count,
    request_params,
    response_schema,
    seq,
    served_model,
    strict_schema_problems,
    text,
    unexpected,
    usage,
)
from bio_claim_check.engine.llm.errors import LlmRequestError
from bio_claim_check.engine.llm.messages import FinishReason, LlmRequest, LlmResponse
from bio_claim_check.engine.llm.usage import Usage

_INCOMPLETE: Mapping[str, FinishReason] = {
    "max_output_tokens": FinishReason.LENGTH,
    "content_filter": FinishReason.CONTENT_FILTER,
}


def encode_request(request: LlmRequest) -> dict[str, JsonValue]:
    """The `responses.create` keyword arguments for `request`."""
    deployment = request.model.deployment
    params = request_params(request)
    if params.temperature is not None and params.reasoning_effort is not None:
        raise LlmRequestError(f"{deployment}: temperature and reasoning_effort cannot be combined")
    system = [m.content for m in request.messages if m.role == "system"]
    body: dict[str, JsonValue] = {
        "model": deployment,
        "input": [{"role": m.role, "content": m.content} for m in request.messages if m.role != "system"],
        "store": False,
    }
    if system:
        body["instructions"] = system[0]
    if params.max_output_tokens is not None:
        body["max_output_tokens"] = params.max_output_tokens
    if params.temperature is not None:
        body["temperature"] = params.temperature
    if params.reasoning_effort is not None:
        body["reasoning"] = {"effort": params.reasoning_effort}
    if (structured := response_schema(request)) is not None:
        name, schema = structured
        if problems := strict_schema_problems(schema):
            raise LlmRequestError(f"{deployment}: schema {name} is not strict: {list(problems)}")
        body["text"] = {"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}}
    return body


def decode_usage(raw_usage: Mapping[str, JsonValue], deployment: str) -> Usage:
    input_details = raw_usage.get("input_tokens_details")
    output_details = raw_usage.get("output_tokens_details")
    cached = (
        obj(input_details, "usage.input_tokens_details", deployment).get("cached_tokens")
        if input_details is not None
        else None
    )
    reasoning = (
        obj(output_details, "usage.output_tokens_details", deployment).get("reasoning_tokens")
        if output_details is not None
        else None
    )
    input_tokens = count(raw_usage.get("input_tokens"), "usage.input_tokens", deployment)
    output_tokens = count(raw_usage.get("output_tokens"), "usage.output_tokens", deployment)
    total = optional_count(raw_usage.get("total_tokens"), "usage.total_tokens", deployment)
    if total is not None and total != input_tokens + output_tokens:
        raise unexpected(deployment, "usage.total_tokens", "is not input_tokens + output_tokens")
    return usage(
        deployment,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=optional_count(
            reasoning, "usage.output_tokens_details.reasoning_tokens", deployment
        ),
        cached_input_tokens=optional_count(cached, "usage.input_tokens_details.cached_tokens", deployment)
        or 0,
    )


def _output(raw: Mapping[str, JsonValue], deployment: str) -> tuple[str, bool]:
    """The answer text (message `output_text` parts, in order) and whether any part was a refusal."""
    parts: list[str] = []
    refused = False
    for i, item_value in enumerate(seq(raw.get("output", []), "output", deployment)):
        item = obj(item_value, f"output[{i}]", deployment)
        kind = item.get("type")
        if kind == "reasoning":
            continue  # reasoning is never part of the answer (I54)
        if kind != "message":
            raise unexpected(deployment, f"output[{i}].type", "is not a message or reasoning item")
        for j, part_value in enumerate(seq(item.get("content"), f"output[{i}].content", deployment)):
            part = obj(part_value, f"output[{i}].content[{j}]", deployment)
            part_kind = part.get("type")
            if part_kind == "output_text":
                parts.append(text(part.get("text"), f"output[{i}].content[{j}].text", deployment))
            elif part_kind == "refusal":
                refused = True
            else:
                raise unexpected(
                    deployment, f"output[{i}].content[{j}].type", "is not output_text or refusal"
                )
    return "".join(parts), refused


def _finish(raw: Mapping[str, JsonValue], refused: bool, deployment: str) -> FinishReason:
    status = raw.get("status")
    if status == "completed":
        return FinishReason.CONTENT_FILTER if refused else FinishReason.STOP
    if status == "incomplete":
        details = obj(raw.get("incomplete_details"), "incomplete_details", deployment)
        reason = details.get("reason")
        if isinstance(reason, str) and reason in _INCOMPLETE:
            return _INCOMPLETE[reason]
        raise unexpected(deployment, "incomplete_details.reason", "is not a known reason")
    raise unexpected(deployment, "status", "is not completed or incomplete")


def decode_response(raw: Mapping[str, JsonValue], deployment: str) -> LlmResponse:
    """The normalised response; any shape this codec does not know raises `llm.unexpected_response`."""
    answer, refused = _output(raw, deployment)
    finish = _finish(raw, refused, deployment)
    return LlmResponse(
        text=answer,
        usage=decode_usage(obj(raw.get("usage"), "usage", deployment), deployment),
        finish_reason=finish,
        deployment=deployment,
        served_model=served_model(raw),
    )
