"""[RING:engine/llm] The request and response every client, cache and processor shares.

Why: one frozen shape makes every LLM call readable and replayable. `LlmRequest` holds only what a
provider sees plus `repeat_idx` (so repeats are distinct cache entries, review #1) and a provenance-only
prompt reference. Role order is validated here, so a request that one provider would reject (Anthropic
needs alternating user/assistant turns) cannot be built for any of them.
Must not: know about claims, papers or labels, or call a provider.

Pure values: makes no provider call. (It is LLM vocabulary, so it does not carry the
ADR 0003 deterministic marker.)
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Annotated, Literal, Self, cast

from pydantic import Field, JsonValue, model_validator

from bio_claim_check.common.models import FrozenJson, NonBlankStr, Sha256Hex, ValidatedModel, thaw
from bio_claim_check.engine.llm.model_spec import ModelIdentity, ModelSpec
from bio_claim_check.engine.llm.usage import Usage


class FinishReason(StrEnum):
    """Why the provider stopped (normalised by each S09 codec)."""

    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"


class Message(ValidatedModel):
    role: Literal["system", "user", "assistant"]
    content: NonBlankStr


class PromptRef(ValidatedModel):
    """Which template produced the messages. Provenance only: not in the cache key (the text already is)."""

    name: NonBlankStr
    version: Annotated[int, Field(strict=True, ge=1)]
    sha256: Sha256Hex


class LlmRequest(ValidatedModel):
    model: ModelIdentity
    messages: tuple[Message, ...]
    params: FrozenJson = Field(default_factory=dict, validate_default=True)
    response_schema: FrozenJson | None = None
    schema_name: NonBlankStr | None = None
    seed: Annotated[int, Field(strict=True)] | None = None
    repeat_idx: Annotated[int, Field(strict=True, ge=0)] = 0
    prompt: PromptRef | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if (self.response_schema is None) != (self.schema_name is None):
            raise ValueError("schema_name is required exactly when response_schema is given")
        roles = [m.role for m in self.messages]
        body = roles[1:] if roles[:1] == ["system"] else roles
        expected = ["user" if i % 2 == 0 else "assistant" for i in range(len(body))]
        if not body or body != expected or body[-1] != "user":
            raise ValueError(
                "messages must be an optional leading system message, then user/assistant turns "
                f"alternating from user and ending with user; got {roles}"
            )
        return self

    def cache_payload(self) -> dict[str, JsonValue]:
        """Every request-shaping field (incl. `repeat_idx`), and nothing provenance-only (I43)."""
        return self.model_dump(mode="json", exclude={"prompt"})

    def with_messages(self, messages: Sequence[Message]) -> Self:
        return type(self).model_validate({**self.model_dump(), "messages": tuple(messages)})

    def with_schema(self, name: str, schema: Mapping[str, JsonValue]) -> Self:
        fields = {**self.model_dump(), "schema_name": name, "response_schema": schema}
        return type(self).model_validate(fields)


class LlmResponse(ValidatedModel):
    """One completion. `usage` is what producing this text consumed.

    `cache_hit` and `billed_usage` are set by the caching client and never stored in the cache:
    a hit was not paid for by this run; `billed_usage` is set only when this run paid for a live call but
    another writer stored its answer first (first write wins), so the text is theirs and the bill is ours.
    `served_model` is the model name the provider reported (provenance only; not in the cache key).
    """

    text: str
    usage: Usage
    finish_reason: FinishReason
    deployment: NonBlankStr
    served_model: NonBlankStr | None = None
    cache_hit: bool = False
    billed_usage: Usage | None = None

    @model_validator(mode="after")
    def _billing(self) -> Self:
        if self.cache_hit and self.billed_usage is not None:
            raise ValueError("a cache hit bills nothing")
        return self

    @property
    def paid_usage(self) -> Usage | None:
        """What this run was billed for; None for a cache hit."""
        if self.cache_hit:
            return None
        return self.usage if self.billed_usage is None else self.billed_usage


def request_for(
    spec: ModelSpec,
    messages: Sequence[Message],
    *,
    params: Mapping[str, JsonValue] | None = None,
    seed: int | None = None,
    repeat_idx: int = 0,
    prompt: PromptRef | None = None,
) -> LlmRequest:
    """A request for `spec`: its default params, overridden key by key by the call's `params`."""
    merged: dict[str, JsonValue] = {**cast(dict[str, JsonValue], thaw(spec.params)), **(params or {})}
    return LlmRequest(
        model=spec.identity(),
        messages=tuple(messages),
        params=merged,
        seed=seed,
        repeat_idx=repeat_idx,
        prompt=prompt,
    )
