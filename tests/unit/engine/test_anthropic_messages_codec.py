"""The Messages-API codec: forced tool use (D6, D7), no thinking (I54), stop reasons (I53), usage (I52)."""

from typing import Any, cast

import pytest

from bio_claim_check.common.models import ValidatedModel
from bio_claim_check.engine.llm.anthropic_messages_codec import (
    decode_response,
    decode_usage,
    encode_request,
    forced_tool,
)
from bio_claim_check.engine.llm.errors import LlmRequestError, LlmUnexpectedResponseError
from bio_claim_check.engine.llm.messages import FinishReason, LlmRequest, Message
from bio_claim_check.engine.llm.model_spec import ModelIdentity, Provider
from bio_claim_check.engine.llm.usage import Usage

pytestmark = pytest.mark.unit

MODEL = ModelIdentity(provider=Provider.FOUNDRY_ANTHROPIC, deployment="claude-x", model_version="v1")
SYSTEM_AND_USER = (Message(role="system", content="S"), Message(role="user", content="U"))
BUDGET: dict[str, Any] = {"max_output_tokens": 64}


class Reply(ValidatedModel):
    ok: bool


def _request(**fields: Any) -> LlmRequest:
    messages = fields.pop("messages", SYSTEM_AND_USER)
    params = fields.pop("params", BUDGET)
    return LlmRequest(model=MODEL, messages=messages, params=params, **fields)


def _structured() -> LlmRequest:
    return _request().with_schema("Reply", Reply.model_json_schema())


def _tool_use(payload: object, name: str = "Reply") -> dict[str, Any]:
    return {"type": "tool_use", "id": "toolu_0", "name": name, "input": payload}


def _raw(**fields: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "model": "claude-x-v1",
        "stop_reason": "tool_use",
        "content": [_tool_use({"ok": True})],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    return raw | fields


def test_a_plain_request_puts_the_system_prompt_in_system_and_requires_a_budget() -> None:
    assert encode_request(_request()) == {
        "model": "claude-x",
        "system": "S",
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "U"}],
    }


def test_structured_output_is_one_forced_tool_and_no_thinking() -> None:
    body = encode_request(_structured())
    schema = Reply.model_json_schema()
    assert body["tools"] == [
        {"name": "Reply", "description": "Record the answer as Reply.", "input_schema": schema}
    ]
    assert body["tool_choice"] == {"type": "tool", "name": "Reply"}
    assert "thinking" not in body
    assert forced_tool(_structured()) == "Reply"
    assert forced_tool(_request()) is None


def test_a_repair_turn_is_plain_messages() -> None:
    turns = (
        Message(role="user", content="U"),
        Message(role="assistant", content="{}"),
        Message(role="user", content="fix it"),
    )
    body = encode_request(_request(messages=turns, params={"max_output_tokens": 8, "temperature": 0.5}))
    assert "system" not in body
    assert body["temperature"] == 0.5
    messages = cast(list[dict[str, str]], body["messages"])
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]


@pytest.mark.parametrize(
    ("request_", "match"),
    [
        (lambda: _request(params={}), "max_output_tokens is required"),
        (lambda: _request(params=BUDGET | {"reasoning_effort": "low"}), "needs thinking"),
        (lambda: _request(params=BUDGET | {"stop": ["x"]}), "unsupported request params"),
        (lambda: _request(seed=1), "seed"),
        (lambda: _request().with_schema("bad name", Reply.model_json_schema()), "valid tool name"),
        (lambda: _request().with_schema("List", {"type": "array"}), "JSON object"),
    ],
)
def test_a_request_it_cannot_send_faithfully_is_refused(request_: Any, match: str) -> None:
    with pytest.raises(LlmRequestError, match=match):
        encode_request(request_())


@pytest.mark.parametrize(
    ("raw_usage", "expected"),
    [
        ({"input_tokens": 10, "output_tokens": 5}, Usage(input_tokens=10, output_tokens=5)),
        (
            {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": None},
            Usage(input_tokens=10, output_tokens=5),
        ),
        (
            {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_input_tokens": 30,
                "cache_creation_input_tokens": 7,
            },
            Usage(input_tokens=47, output_tokens=5, cached_input_tokens=30),
        ),
        (
            {
                "input_tokens": 3,
                "output_tokens": 5,
                "cache_creation_input_tokens": 0,
                "service_tier": "standard",
            },
            Usage(input_tokens=3, output_tokens=5),
        ),
    ],
)
def test_usage_adds_cache_reads_and_writes_back_into_input(
    raw_usage: dict[str, Any], expected: Usage
) -> None:
    assert decode_usage(raw_usage, "claude-x") == expected


@pytest.mark.parametrize(
    "raw_usage",
    [
        {"output_tokens": 5},
        {"input_tokens": 1, "output_tokens": "5"},
        {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": -1},
    ],
)
def test_impossible_usage_is_an_unexpected_response(raw_usage: dict[str, Any]) -> None:
    with pytest.raises(LlmUnexpectedResponseError, match="usage"):
        decode_usage(raw_usage, "claude-x")


def test_the_forced_tool_input_is_the_answer_as_canonical_json() -> None:
    raw = _raw(content=[{"type": "text", "text": "Sure."}, _tool_use({"z": "é", "a": [1]})])
    response = decode_response(raw, "claude-x", tool="Reply")
    assert response.text == '{"a":[1],"z":"é"}'
    assert (response.finish_reason, response.served_model) == (FinishReason.STOP, "claude-x-v1")


def test_a_missing_tool_call_decodes_to_empty_text_for_the_runner_to_repair() -> None:
    raw = _raw(stop_reason="end_turn", content=[{"type": "text", "text": '{"ok": true}'}])
    assert decode_response(raw, "claude-x", tool="Reply").text == ""


def test_an_input_wrapper_is_not_unwrapped() -> None:
    raw = _raw(content=[_tool_use({"input": '{"ok": true}'})])
    assert decode_response(raw, "claude-x", tool="Reply").text == '{"input":"{\\"ok\\": true}"}'


def test_free_text_concatenates_text_blocks() -> None:
    raw = _raw(stop_reason="end_turn", content=[{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
    assert decode_response(raw, "claude-x", tool=None).text == "ab"


@pytest.mark.parametrize(
    ("stop", "finish"),
    [
        ("end_turn", FinishReason.STOP),
        ("tool_use", FinishReason.STOP),
        ("max_tokens", FinishReason.LENGTH),
        ("model_context_window_exceeded", FinishReason.LENGTH),
        ("refusal", FinishReason.CONTENT_FILTER),
    ],
)
def test_stop_reasons_map_totally(stop: str, finish: FinishReason) -> None:
    assert decode_response(_raw(stop_reason=stop), "claude-x", tool="Reply").finish_reason is finish


@pytest.mark.parametrize(
    ("fields", "tool"),
    [
        ({"stop_reason": "stop_sequence"}, "Reply"),
        ({"stop_reason": "pause_turn"}, "Reply"),
        ({"stop_reason": None}, "Reply"),
        ({"content": [_tool_use({"ok": True}, name="Other")]}, "Reply"),
        ({"content": [_tool_use({"ok": True})]}, None),
        ({"content": [_tool_use({"ok": True}), _tool_use({"ok": False})]}, "Reply"),
        ({"content": [_tool_use("not an object")]}, "Reply"),
        ({"content": [{"type": "thinking", "thinking": "..."}]}, "Reply"),
        ({"content": [{"type": "redacted_thinking", "data": "..."}]}, "Reply"),
        ({"content": [{"type": "text", "text": 1}]}, None),
        ({"content": None}, "Reply"),
        ({"usage": None}, "Reply"),
    ],
)
def test_unknown_shapes_fail_closed(fields: dict[str, Any], tool: str | None) -> None:
    with pytest.raises(LlmUnexpectedResponseError):
        decode_response(_raw(**fields), "claude-x", tool=tool)
