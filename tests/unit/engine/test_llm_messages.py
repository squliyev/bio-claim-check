"""Request shape (I47), cache payload and response billing rules."""

import pytest
from pydantic import ValidationError
from tests.support.llm import IDENTITY, request, response, spec, user

from bio_claim_check.engine.llm.messages import (
    LlmRequest,
    LlmResponse,
    Message,
    PromptRef,
    request_for,
)
from bio_claim_check.engine.llm.usage import Usage

pytestmark = pytest.mark.unit

SYSTEM = Message(role="system", content="Be careful.")
ASSISTANT = Message(role="assistant", content="{}")
REF = PromptRef(name="verify", version=1, sha256="a" * 64)


@pytest.mark.parametrize(
    "messages",
    [
        (user(),),
        (SYSTEM, user()),
        (user(), ASSISTANT, user()),
        (SYSTEM, user(), ASSISTANT, user()),
    ],
)
def test_valid_role_shapes(messages: tuple[Message, ...]) -> None:
    assert LlmRequest(model=IDENTITY, messages=messages).messages == messages


@pytest.mark.parametrize(
    "messages",
    [
        (),
        (SYSTEM,),
        (ASSISTANT,),
        (user(), ASSISTANT),
        (user(), user()),
        (SYSTEM, SYSTEM, user()),
        (user(), SYSTEM),
        (ASSISTANT, user()),
    ],
)
def test_invalid_role_shapes_are_rejected(messages: tuple[Message, ...]) -> None:
    with pytest.raises(ValidationError, match=r"alternating"):
        LlmRequest(model=IDENTITY, messages=messages)


def test_blank_message_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Message(role="user", content=" ")


@pytest.mark.parametrize("fields", [{"response_schema": {"type": "object"}}, {"schema_name": "Out"}])
def test_schema_and_its_name_come_together(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match=r"schema_name"):
        LlmRequest.model_validate({"model": IDENTITY, "messages": (user(),), **fields})


@pytest.mark.parametrize("value", [-1, True, 1.0, "1"])
def test_repeat_idx_is_a_strict_non_negative_int(value: object) -> None:
    with pytest.raises(ValidationError):
        LlmRequest.model_validate({"model": IDENTITY, "messages": (user(),), "repeat_idx": value})


@pytest.mark.parametrize("value", [0, True, 1.0])
def test_prompt_version_is_a_strict_positive_int(value: object) -> None:
    with pytest.raises(ValidationError):
        PromptRef.model_validate({"name": "n", "version": value, "sha256": "a" * 64})


def test_cache_payload_has_every_shaping_field_and_no_provenance() -> None:
    req = LlmRequest(model=IDENTITY, messages=(user(),), prompt=REF, seed=7, repeat_idx=2)
    payload = req.cache_payload()
    assert set(payload) == {
        "model",
        "messages",
        "params",
        "response_schema",
        "schema_name",
        "seed",
        "repeat_idx",
    }
    assert payload["repeat_idx"] == 2


def test_with_messages_and_with_schema_return_new_validated_requests() -> None:
    req = request()
    longer = req.with_messages((*req.messages, ASSISTANT, user("again")))
    assert len(longer.messages) == 3
    assert len(req.messages) == 1
    with pytest.raises(ValidationError):
        req.with_messages((*req.messages, ASSISTANT))
    typed = req.with_schema("Out", {"type": "object", "properties": {"a": {"type": "string"}}})
    assert typed.schema_name == "Out"
    assert req.schema_name is None
    assert typed.response_schema is not None
    with pytest.raises(TypeError):
        typed.response_schema["properties"]["a"] = {}  # type: ignore[index]  # proving nested schema is read-only


def test_request_for_merges_params_with_the_call_winning() -> None:
    req = request_for(spec(), (user(),), params={"temperature": 1, "max_output_tokens": 50}, repeat_idx=1)
    assert req.model == spec().identity()
    assert req.cache_payload()["params"] == {
        "temperature": 1,
        "max_output_tokens": 50,
        "nested": {"top_p": 1},
    }
    assert req.repeat_idx == 1
    assert request_for(spec(), (user(),)).cache_payload()["params"] == {
        "temperature": 0,
        "nested": {"top_p": 1},
    }


def test_paid_usage_reflects_hit_live_and_lost_race() -> None:
    live = response()
    assert live.paid_usage == live.usage
    hit = LlmResponse.model_validate({**live.model_dump(), "cache_hit": True})
    assert hit.paid_usage is None
    ours = Usage(input_tokens=1, output_tokens=1)
    raced = LlmResponse.model_validate({**live.model_dump(), "billed_usage": ours.model_dump()})
    assert raced.paid_usage == ours


def test_a_hit_cannot_also_be_billed() -> None:
    with pytest.raises(ValidationError, match=r"bills nothing"):
        LlmResponse.model_validate(
            {**response().model_dump(), "cache_hit": True, "billed_usage": Usage().model_dump()}
        )
