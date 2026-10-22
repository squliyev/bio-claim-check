"""The Responses-API codec: request pitfalls (I54, D2 to D5), finish mapping (I53), usage shapes (I52)."""

from typing import Any

import pytest

from bio_claim_check.common.models import ValidatedModel
from bio_claim_check.engine.llm.codec_support import strict_schema_problems
from bio_claim_check.engine.llm.errors import LlmRequestError, LlmUnexpectedResponseError
from bio_claim_check.engine.llm.messages import FinishReason, LlmRequest, Message
from bio_claim_check.engine.llm.model_spec import ModelIdentity, Provider
from bio_claim_check.engine.llm.openai_responses_codec import decode_response, decode_usage, encode_request
from bio_claim_check.engine.llm.usage import Usage

pytestmark = pytest.mark.unit

MODEL = ModelIdentity(provider=Provider.FOUNDRY_OPENAI, deployment="gpt-x", model_version="2026-01-01")
SYSTEM_AND_USER = (Message(role="system", content="S"), Message(role="user", content="U"))
REFUSAL: dict[str, Any] = {"type": "refusal", "refusal": "no"}


class Reply(ValidatedModel):
    ok: bool


def _request(**fields: Any) -> LlmRequest:
    messages = fields.pop("messages", SYSTEM_AND_USER)
    return LlmRequest(model=MODEL, messages=messages, **fields)


def _part(text: str) -> dict[str, Any]:
    return {"type": "output_text", "text": text}


def _message(*parts: dict[str, Any]) -> dict[str, Any]:
    return {"type": "message", "role": "assistant", "content": list(parts)}


def _incomplete(reason: object) -> dict[str, Any]:
    return {"status": "incomplete", "incomplete_details": {"reason": reason}}


def _raw(**fields: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "model": "gpt-x-2026-01-01",
        "status": "completed",
        "output": [_message(_part("hi"))],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    return raw | fields


def test_a_plain_request_is_stateless_and_puts_the_system_prompt_in_instructions() -> None:
    assert encode_request(_request()) == {
        "model": "gpt-x",
        "instructions": "S",
        "input": [{"role": "user", "content": "U"}],
        "store": False,
    }


def test_a_repair_turn_is_plain_messages_without_ids() -> None:
    turns = (
        Message(role="user", content="U"),
        Message(role="assistant", content="{}"),
        Message(role="user", content="fix it"),
    )
    body = encode_request(_request(messages=turns))
    assert "instructions" not in body
    assert body["input"] == [
        {"role": "user", "content": "U"},
        {"role": "assistant", "content": "{}"},
        {"role": "user", "content": "fix it"},
    ]


@pytest.mark.parametrize("forbidden", ["previous_response_id", "include", "id"])
def test_reasoning_is_never_replayed_or_kept(forbidden: str) -> None:
    body = encode_request(_request(params={"max_output_tokens": 9, "reasoning_effort": "low"}))
    assert forbidden not in body
    assert body["store"] is False


def test_params_map_onto_the_api_and_effort_is_nested() -> None:
    body = encode_request(_request(params={"max_output_tokens": 9, "reasoning_effort": "low"}))
    assert body["max_output_tokens"] == 9
    assert body["reasoning"] == {"effort": "low"}
    assert encode_request(_request(params={"temperature": 0}))["temperature"] == 0.0


@pytest.mark.parametrize(
    ("fields", "match"),
    [
        ({"params": {"top_p": 1}}, "unsupported request params"),
        ({"params": {"max_output_tokens": 0}}, "positive integer"),
        ({"params": {"max_output_tokens": True}}, "positive integer"),
        ({"params": {"temperature": 3}}, r"\[0, 2\]"),
        ({"params": {"temperature": "hot"}}, r"\[0, 2\]"),
        ({"params": {"reasoning_effort": " "}}, "non-blank"),
        ({"params": {"temperature": 0.2, "reasoning_effort": "low"}}, "cannot be combined"),
        ({"seed": 7}, "seed"),
    ],
)
def test_a_request_it_cannot_send_faithfully_is_refused(fields: dict[str, Any], match: str) -> None:
    with pytest.raises(LlmRequestError, match=match):
        encode_request(_request(**fields))


def test_structured_output_is_a_strict_json_schema() -> None:
    schema = Reply.model_json_schema()
    body = encode_request(_request().with_schema("Reply", schema))
    expected = {"type": "json_schema", "name": "Reply", "schema": schema, "strict": True}
    assert body["text"] == {"format": expected}


def test_a_non_strict_schema_is_refused_naming_the_path() -> None:
    class Loose(ValidatedModel):
        ok: bool
        note: str | None = None

    with pytest.raises(LlmRequestError, match=r"\$: every property must be required; optional \['note'\]"):
        encode_request(_request().with_schema("Loose", Loose.model_json_schema()))


def test_the_strict_pre_check_walks_nested_schemas() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["xs", "y"],
        "properties": {
            "xs": {"type": "array", "items": {"type": "object", "properties": {"a": {"type": "string"}}}},
            "y": {"anyOf": [{"$ref": "#/$defs/Y"}, {"type": "null"}]},
        },
        "$defs": {"Y": {"type": "object", "additionalProperties": False, "required": [], "properties": {}}},
        "allOf": [{"properties": {"z": {}}, "additionalProperties": False, "required": "z"}],
    }
    assert strict_schema_problems(schema) == (
        "$.properties.xs.items: additionalProperties must be false",
        "$.properties.xs.items: every property must be required; optional ['a']",
        "$.allOf[0]: every property must be required; optional ['z']",
    )


@pytest.mark.parametrize(
    ("raw_usage", "expected"),
    [
        ({"input_tokens": 10, "output_tokens": 5}, Usage(input_tokens=10, output_tokens=5)),
        (
            {
                "input_tokens": 10,
                "output_tokens": 5,
                "input_tokens_details": {"cached_tokens": 4},
                "output_tokens_details": {"reasoning_tokens": 3},
                "total_tokens": 15,
            },
            Usage(input_tokens=10, output_tokens=5, reasoning_tokens=3, cached_input_tokens=4),
        ),
        (
            {"input_tokens": 1, "output_tokens": 0, "input_tokens_details": {}, "output_tokens_details": {}},
            Usage(input_tokens=1),
        ),
        (
            {"input_tokens": 1, "output_tokens": 2, "output_tokens_details": {"reasoning_tokens": 0}},
            Usage(input_tokens=1, output_tokens=2, reasoning_tokens=0),
        ),
    ],
)
def test_usage_shapes_normalise_and_unreported_reasoning_stays_none(
    raw_usage: dict[str, Any], expected: Usage
) -> None:
    assert decode_usage(raw_usage, "gpt-x") == expected


@pytest.mark.parametrize(
    "raw_usage",
    [
        {"output_tokens": 5},
        {"input_tokens": -1, "output_tokens": 5},
        {"input_tokens": True, "output_tokens": 5},
        {"input_tokens": 1, "output_tokens": 5, "input_tokens_details": {"cached_tokens": 2}},
        {"input_tokens": 1, "output_tokens": 1, "output_tokens_details": {"reasoning_tokens": 2}},
        {"input_tokens": 1, "output_tokens": 1, "output_tokens_details": "x"},
    ],
)
def test_impossible_usage_is_an_unexpected_response(raw_usage: dict[str, Any]) -> None:
    with pytest.raises(LlmUnexpectedResponseError, match="usage"):
        decode_usage(raw_usage, "gpt-x")


def test_a_completed_response_decodes_with_the_served_model() -> None:
    response = decode_response(_raw(), "gpt-x")
    assert (response.text, response.finish_reason) == ("hi", FinishReason.STOP)
    assert response.served_model == "gpt-x-2026-01-01"
    assert response.usage == Usage(input_tokens=10, output_tokens=5)
    assert decode_response(_raw(model=" "), "gpt-x").served_model is None


def test_text_parts_concatenate_in_order_and_reasoning_items_are_skipped() -> None:
    reasoning: dict[str, Any] = {"type": "reasoning", "id": "rs_1", "summary": []}
    output = [reasoning, _message(_part("a"), _part("b")), _message(_part("c"))]
    assert decode_response(_raw(output=output), "gpt-x").text == "abc"


@pytest.mark.parametrize(
    ("fields", "finish"),
    [
        (_incomplete("max_output_tokens"), FinishReason.LENGTH),
        (_incomplete("content_filter"), FinishReason.CONTENT_FILTER),
        ({"output": [_message(REFUSAL)]}, FinishReason.CONTENT_FILTER),
        ({"output": [_message(_part("x"), REFUSAL)]}, FinishReason.CONTENT_FILTER),
    ],
)
def test_truncation_filters_and_refusals_are_never_stop(fields: dict[str, Any], finish: FinishReason) -> None:
    assert decode_response(_raw(**fields), "gpt-x").finish_reason is finish


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "failed"},
        {"status": "in_progress"},
        {"status": "cancelled"},
        {"status": "queued"},
        {"status": None},
        _incomplete("max_messages"),
        {"status": "incomplete", "incomplete_details": None},
        {"output": [{"type": "function_call", "name": "f"}]},
        {"output": [_message({"type": "output_audio"})]},
        {"output": [_message({"type": "output_text", "text": 3})]},
        {"output": [{"type": "message", "content": "hi"}]},
        {"output": ["hi"]},
        {"output": {}},
        {"usage": None},
    ],
)
def test_unknown_states_fail_closed(fields: dict[str, Any]) -> None:
    with pytest.raises(LlmUnexpectedResponseError):
        decode_response(_raw(**fields), "gpt-x")


def test_an_error_never_quotes_the_raw_value() -> None:
    sentinel = "SENTINEL-abstract-text"
    with pytest.raises(LlmUnexpectedResponseError) as caught:
        decode_response(_raw(status=sentinel), "gpt-x")
    assert sentinel not in str(caught.value)
