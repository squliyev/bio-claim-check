"""[RING:engine/llm] What both provider codecs share: typed reads of raw JSON and the generic params rules.

Why: each codec decodes an untyped provider dict; reading it through these helpers turns every surprise
(a missing field, a string where a count belongs, a boolean posing as an integer) into one typed
`LlmUnexpectedResponseError` that names the JSON path, never into a `KeyError` or a silently wrong
number (I53). The generic request params (`max_output_tokens`, `temperature`, `reasoning_effort`) are
validated once here, so an unknown or mistyped key is refused for every provider alike (D2) and a seed
is never silently dropped (D3).
Must not: know a provider's field names, import a driver, or quote a raw value into an error (it may
echo the prompt).

Pure logic: makes no provider call. (It is LLM vocabulary, so it does not carry the
ADR 0003 deterministic marker.)
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, cast

from pydantic import JsonValue, ValidationError

from bio_claim_check.common.models import thaw
from bio_claim_check.engine.llm.errors import LlmRequestError, LlmUnexpectedResponseError
from bio_claim_check.engine.llm.messages import LlmRequest
from bio_claim_check.engine.llm.usage import Usage

PARAM_KEYS: Final = frozenset({"max_output_tokens", "temperature", "reasoning_effort"})


@dataclass(frozen=True, slots=True)
class Params:
    """The generic request params, validated; None = not set (the provider's default applies)."""

    max_output_tokens: int | None = None
    temperature: float | None = None
    reasoning_effort: str | None = None


def request_params(request: LlmRequest) -> Params:
    """The validated generic params of `request`; an unknown key, a bad value or a seed is refused."""
    deployment = request.model.deployment
    if request.seed is not None:
        raise LlmRequestError(f"{deployment}: a seed was set, but the provider API has none to honour")
    params = request.params
    if unknown := sorted(set(params) - PARAM_KEYS):
        raise LlmRequestError(
            f"{deployment}: unsupported request params {unknown}; known {sorted(PARAM_KEYS)}"
        )
    max_tokens = params.get("max_output_tokens")
    if max_tokens is not None and (not _is_int(max_tokens) or cast(int, max_tokens) < 1):
        raise LlmRequestError(f"{deployment}: max_output_tokens must be a positive integer")
    temperature = params.get("temperature")
    if temperature is not None and (not _is_number(temperature) or not 0 <= cast(float, temperature) <= 2):
        raise LlmRequestError(f"{deployment}: temperature must be a number in [0, 2]")
    effort = params.get("reasoning_effort")
    if effort is not None and (not isinstance(effort, str) or not effort.strip()):
        raise LlmRequestError(f"{deployment}: reasoning_effort must be a non-blank string")
    return Params(
        max_output_tokens=cast(int | None, max_tokens),
        temperature=None if temperature is None else float(cast(float, temperature)),
        reasoning_effort=effort,
    )


def response_schema(request: LlmRequest) -> tuple[str, dict[str, JsonValue]] | None:
    """The request's (schema name, plain JSON schema), or None for a free-text request."""
    if request.response_schema is None or request.schema_name is None:
        return None
    return request.schema_name, cast(dict[str, JsonValue], thaw(request.response_schema))


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return (_is_int(value) or isinstance(value, float)) and math.isfinite(cast(float, value))


def unexpected(deployment: str, path: str, problem: str) -> LlmUnexpectedResponseError:
    return LlmUnexpectedResponseError(f"{deployment}: response field {path} {problem}")


def obj(value: JsonValue | None, path: str, deployment: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, dict):
        raise unexpected(deployment, path, "is not an object")
    return value


def seq(value: JsonValue | None, path: str, deployment: str) -> Sequence[JsonValue]:
    if not isinstance(value, list):
        raise unexpected(deployment, path, "is not a list")
    return value


def text(value: JsonValue | None, path: str, deployment: str) -> str:
    if not isinstance(value, str):
        raise unexpected(deployment, path, "is not a string")
    return value


def count(value: JsonValue | None, path: str, deployment: str) -> int:
    if not _is_int(value) or cast(int, value) < 0:
        raise unexpected(deployment, path, "is not a non-negative integer")
    return cast(int, value)


def optional_count(value: JsonValue | None, path: str, deployment: str) -> int | None:
    return None if value is None else count(value, path, deployment)


def served_model(raw: Mapping[str, JsonValue]) -> str | None:
    """The provider-reported model name (provenance only); None when absent or blank."""
    model = raw.get("model")
    return model if isinstance(model, str) and model.strip() else None


def usage(deployment: str, **tokens: int | None) -> Usage:
    """A `Usage` from decoded counts; counts that break the subset rules are an unexpected response."""
    try:
        return Usage.model_validate(tokens)
    except ValidationError:
        raise unexpected(deployment, "usage", "breaks reasoning ⊆ output or cached ⊆ input") from None


def strict_schema_problems(schema: Mapping[str, JsonValue], path: str = "$") -> tuple[str, ...]:
    """Where `schema` breaks strict structured output: every object closed and all its properties required."""
    problems: list[str] = []
    properties = schema.get("properties")
    if schema.get("type") == "object" or isinstance(properties, dict):
        if schema.get("additionalProperties") is not False:
            problems.append(f"{path}: additionalProperties must be false")
        names = set(properties) if isinstance(properties, dict) else set[str]()
        required = schema.get("required", [])
        listed = {r for r in required if isinstance(r, str)} if isinstance(required, list) else set[str]()
        if missing := sorted(names - listed):
            problems.append(f"{path}: every property must be required; optional {missing}")
    for key in ("properties", "$defs", "definitions"):
        children = schema.get(key)
        if isinstance(children, dict):
            for name, child in sorted(children.items()):
                if isinstance(child, dict):
                    problems.extend(strict_schema_problems(child, f"{path}.{key}.{name}"))
    items = schema.get("items")
    if isinstance(items, dict):
        problems.extend(strict_schema_problems(items, f"{path}.items"))
    for key in ("anyOf", "allOf", "oneOf"):
        options = schema.get(key)
        if isinstance(options, list):
            for i, option in enumerate(options):
                if isinstance(option, dict):
                    problems.extend(strict_schema_problems(option, f"{path}.{key}[{i}]"))
    return tuple(problems)
