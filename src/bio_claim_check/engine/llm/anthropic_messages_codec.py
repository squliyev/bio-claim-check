"""[RING:engine/llm] Everything the backend knows about the Anthropic Messages API, as pure dict mapping.

Why: provider knowledge in one place, unit-tested without the SDK or a network (D1). Structured output
is **forced tool use**: one tool named after the schema, `tool_choice` naming it, and the answer is the
tool's `input` serialised as compact canonical JSON (D6, D7). Thinking is never enabled (it cannot be
combined with a forced tool, and reasoning is never sent or kept, I54), so `reasoning_effort` is
refused. `max_tokens` is mandatory in this API, so `max_output_tokens` is required. A response without
the forced tool call decodes to empty text, which fails validation and earns the runner's one counted
repair; a `{"input": …}` wrapper is not unwrapped. Stop reasons map fail-closed (I53) and usage is
normalised: Anthropic reports cache reads and cache writes outside `input_tokens`, so both are added
back in and cached = cache reads (I52).
Must not: import the SDK, perform I/O, or carry a raw value into an error.

Pure logic: makes no provider call. (It is LLM vocabulary, so it does not carry the
ADR 0003 deterministic marker.)
"""

import re
from collections.abc import Mapping
from typing import Final

from pydantic import JsonValue

from bio_claim_check.common.canonical_json import compact_json
from bio_claim_check.engine.llm.codec_support import (
    count,
    obj,
    optional_count,
    request_params,
    response_schema,
    seq,
    served_model,
    text,
    unexpected,
    usage,
)
from bio_claim_check.engine.llm.errors import LlmRequestError
from bio_claim_check.engine.llm.messages import FinishReason, LlmRequest, LlmResponse
from bio_claim_check.engine.llm.usage import Usage

TOOL_NAME: Final = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_STOP: Mapping[str, FinishReason] = {
    "end_turn": FinishReason.STOP,
    "tool_use": FinishReason.STOP,
    "max_tokens": FinishReason.LENGTH,
    "model_context_window_exceeded": FinishReason.LENGTH,
    "refusal": FinishReason.CONTENT_FILTER,
}


def forced_tool(request: LlmRequest) -> str | None:
    """The tool name a structured request forces, or None for free text."""
    structured = response_schema(request)
    return None if structured is None else structured[0]


def encode_request(request: LlmRequest) -> dict[str, JsonValue]:
    """The `messages.create` keyword arguments for `request`."""
    deployment = request.model.deployment
    params = request_params(request)
    if params.reasoning_effort is not None:
        raise LlmRequestError(
            f"{deployment}: reasoning_effort needs thinking, which forced tool use excludes"
        )
    if params.max_output_tokens is None:
        raise LlmRequestError(f"{deployment}: max_output_tokens is required (the API's max_tokens)")
    system = [m.content for m in request.messages if m.role == "system"]
    body: dict[str, JsonValue] = {
        "model": deployment,
        "max_tokens": params.max_output_tokens,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages if m.role != "system"],
    }
    if system:
        body["system"] = system[0]
    if params.temperature is not None:
        body["temperature"] = params.temperature
    if (structured := response_schema(request)) is not None:
        name, schema = structured
        if not TOOL_NAME.fullmatch(name):
            raise LlmRequestError(f"{deployment}: schema name {name!r} is not a valid tool name")
        if schema.get("type") != "object":
            raise LlmRequestError(f"{deployment}: schema {name} must describe a JSON object (a tool input)")
        body["tools"] = [
            {"name": name, "description": f"Record the answer as {name}.", "input_schema": schema}
        ]
        body["tool_choice"] = {"type": "tool", "name": name}
    return body


def decode_usage(raw_usage: Mapping[str, JsonValue], deployment: str) -> Usage:
    read = optional_count(
        raw_usage.get("cache_read_input_tokens"), "usage.cache_read_input_tokens", deployment
    )
    written = optional_count(
        raw_usage.get("cache_creation_input_tokens"), "usage.cache_creation_input_tokens", deployment
    )
    uncached = count(raw_usage.get("input_tokens"), "usage.input_tokens", deployment)
    return usage(
        deployment,
        input_tokens=uncached + (read or 0) + (written or 0),
        output_tokens=count(raw_usage.get("output_tokens"), "usage.output_tokens", deployment),
        reasoning_tokens=None,  # thinking is never enabled, and the API reports no separate count for it
        cached_input_tokens=read or 0,
    )


def _answer(raw: Mapping[str, JsonValue], tool: str | None, deployment: str) -> str:
    texts: list[str] = []
    inputs: list[str] = []
    for i, block_value in enumerate(seq(raw.get("content"), "content", deployment)):
        block = obj(block_value, f"content[{i}]", deployment)
        kind = block.get("type")
        if kind == "text":
            texts.append(text(block.get("text"), f"content[{i}].text", deployment))
        elif kind == "tool_use" and tool is not None and block.get("name") == tool:
            inputs.append(compact_json(obj(block.get("input"), f"content[{i}].input", deployment)))
        else:
            raise unexpected(deployment, f"content[{i}].type", "is not text or the forced tool call")
    if tool is None:
        return "".join(texts)
    if len(inputs) > 1:
        raise unexpected(deployment, "content", "holds more than one forced tool call")
    return inputs[0] if inputs else ""  # the model ignored the forced tool: fails validation, one repair


def decode_response(raw: Mapping[str, JsonValue], deployment: str, *, tool: str | None) -> LlmResponse:
    """The normalised response; `tool` is the forced tool name (see `forced_tool`) or None."""
    stop = raw.get("stop_reason")
    if not isinstance(stop, str) or stop not in _STOP:
        raise unexpected(deployment, "stop_reason", "is not a known stop reason")
    return LlmResponse(
        text=_answer(raw, tool, deployment),
        usage=decode_usage(obj(raw.get("usage"), "usage", deployment), deployment),
        finish_reason=_STOP[stop],
        deployment=deployment,
        served_model=served_model(raw),
    )
