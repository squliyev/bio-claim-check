"""Runner order, one repair, no repair for truncation/filters, spend on every path (I44)."""

from dataclasses import replace
from decimal import Decimal
from typing import override

import pytest
from pydantic import BaseModel, ConfigDict, field_validator
from tests.support.llm import request, response, spec

from bio_claim_check.common.models import thaw
from bio_claim_check.engine.cache.in_memory_cache import InMemoryCache
from bio_claim_check.engine.cache.policy import CacheMode
from bio_claim_check.engine.llm.caching_llm_client import CachingLlmClient
from bio_claim_check.engine.llm.errors import LlmCallError, LlmFailureKind
from bio_claim_check.engine.llm.messages import FinishReason, LlmRequest, Message
from bio_claim_check.engine.llm.model_spec import ModelIdentity, Provider
from bio_claim_check.engine.llm.scripted_llm_client import ScriptedLlmClient
from bio_claim_check.engine.llm.usage import Spend, Usage
from bio_claim_check.engine.pipeline.base_request_processor import BaseRequestProcessor
from bio_claim_check.engine.pipeline.base_response_processor import BaseResponseProcessor
from bio_claim_check.engine.pipeline.invocation import Invocation
from bio_claim_check.engine.pipeline.llm_runner import (
    EMPTY_REPLY,
    MAX_ATTEMPTS,
    UNDECLARED,
    LlmRunner,
    ProcessorContractError,
    declared_names,
)

pytestmark = pytest.mark.unit

USAGE = Usage(input_tokens=1_000_000, output_tokens=100_000)
CALL_COST = Decimal("2.50") + Decimal("1.0")  # 1M input at 2.50 + 0.1M output at 10 per Mtok


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool


def runner(client: ScriptedLlmClient | CachingLlmClient) -> LlmRunner[str, Out]:
    return LlmRunner[str, Out](client, spec(), Out)


def start() -> Invocation[str]:
    return Invocation(payload="claim", request=request())


class Tag(BaseRequestProcessor[str]):
    def __init__(self, name: str, log: list[str]) -> None:
        self.name, self.log = name, log

    @override
    def process(self, invocation: Invocation[str]) -> Invocation[str]:
        self.log.append(self.name)
        return replace(invocation, payload=f"{invocation.payload}+{self.name}")


class Seen(BaseResponseProcessor[str, Out]):
    def __init__(self, name: str, log: list[str]) -> None:
        self.name, self.log = name, log

    @override
    def process(self, invocation: Invocation[str], output: Out) -> Invocation[str]:
        self.log.append(f"{self.name}:{output.ok}:{invocation.spend.calls}")
        return replace(invocation, payload=f"{invocation.payload}>{self.name}")


def test_valid_first_time_is_one_call_with_schema_from_the_output_type() -> None:
    client = ScriptedLlmClient([response('{"ok": true}', usage=USAGE)])
    out, inv = runner(client).run(start())
    assert out == Out(ok=True)
    assert len(client.requests) == 1
    sent = client.requests[0]
    assert sent.schema_name == "Out"
    assert sent.response_schema is not None
    assert thaw(sent.response_schema) == Out.model_json_schema(mode="validation")
    assert inv.spend.calls == 1
    assert inv.spend.cost == CALL_COST
    assert len(inv.responses) == 1


def test_one_repair_appends_reply_and_instruction() -> None:
    client = ScriptedLlmClient(
        [response('{"ok": "maybe"}', usage=USAGE), response('{"ok": false}', usage=USAGE)]
    )
    out, inv = runner(client).run(start())
    assert out == Out(ok=False)
    first, second = client.requests
    assert second.messages[: len(first.messages)] == first.messages
    reply, fix = second.messages[len(first.messages) :]
    assert reply == Message(role="assistant", content='{"ok": "maybe"}')
    assert fix.role == "user"
    assert "Problems: ok [bool_parsing]." in fix.content
    assert "maybe" not in fix.content
    assert second.response_schema == first.response_schema
    assert inv.spend.calls == 2
    assert inv.spend.cost == 2 * CALL_COST


def test_invalid_twice_raises_with_the_spend_of_both_attempts() -> None:
    client = ScriptedLlmClient([response('{"ok": 3}', usage=USAGE), response('{"nope": 1}', usage=USAGE)])
    with pytest.raises(LlmCallError) as caught:
        runner(client).run(start())
    error = caught.value
    assert error.kind is LlmFailureKind.INVALID_OUTPUT
    assert error.attempts == MAX_ATTEMPTS
    assert error.spend.calls == 2
    assert error.spend.cost == 2 * CALL_COST
    assert set(error.validation) == {("ok", "missing"), (UNDECLARED, "extra_forbidden")}
    assert "nope" not in str(error)  # a model-invented key is model output (I59)


@pytest.mark.parametrize("text", ["not json", "", "   "])
def test_non_json_is_repaired_like_invalid_output(text: str) -> None:
    client = ScriptedLlmClient([response(text, usage=USAGE), response('{"ok": true}', usage=USAGE)])
    out, _ = runner(client).run(start())
    assert out == Out(ok=True)
    reply = client.requests[1].messages[-2]
    assert reply.content == (text if text.strip() else EMPTY_REPLY)


@pytest.mark.parametrize(
    ("finish", "kind"),
    [
        (FinishReason.LENGTH, LlmFailureKind.TRUNCATED),
        (FinishReason.CONTENT_FILTER, LlmFailureKind.CONTENT_FILTERED),
    ],
)
def test_truncation_and_filters_fail_at_once_without_repair(
    finish: FinishReason, kind: LlmFailureKind
) -> None:
    client = ScriptedLlmClient([response('{"ok": true}', finish=finish, usage=USAGE), response(usage=USAGE)])
    with pytest.raises(LlmCallError) as caught:
        runner(client).run(start())
    assert caught.value.kind is kind
    assert caught.value.attempts == 1
    assert caught.value.spend.calls == 1
    assert caught.value.spend.cost == CALL_COST
    assert len(client.requests) == 1


def test_truncation_on_the_repair_attempt_keeps_both_spends() -> None:
    client = ScriptedLlmClient(
        [response("bad", usage=USAGE), response('{"ok": tr', finish=FinishReason.LENGTH, usage=USAGE)]
    )
    with pytest.raises(LlmCallError) as caught:
        runner(client).run(start())
    assert caught.value.kind is LlmFailureKind.TRUNCATED
    assert caught.value.attempts == 2
    assert caught.value.spend.calls == 2


def test_processors_run_in_the_given_order_after_validation() -> None:
    log: list[str] = []
    client = ScriptedLlmClient([response("bad", usage=USAGE), response('{"ok": true}', usage=USAGE)])
    run: LlmRunner[str, Out] = LlmRunner(
        client,
        spec(),
        Out,
        request_processors=[Tag("a", log), Tag("b", log)],
        response_processors=[Seen("x", log), Seen("y", log)],
    )
    _, inv = run.run(start())
    assert log == ["a", "b", "x:True:2", "y:True:2"]  # request side once; response side sees recorded spend
    assert inv.payload == "claim+a+b>x>y"


def test_response_processors_never_see_invalid_output() -> None:
    log: list[str] = []
    client = ScriptedLlmClient([response("bad", usage=USAGE), response("bad", usage=USAGE)])
    run: LlmRunner[str, Out] = LlmRunner(client, spec(), Out, response_processors=[Seen("x", log)])
    with pytest.raises(LlmCallError):
        run.run(start())
    assert log == []


def test_client_errors_propagate_unchanged() -> None:
    with pytest.raises(LookupError):
        runner(ScriptedLlmClient([])).run(start())


def test_the_input_invocation_is_unchanged() -> None:
    client = ScriptedLlmClient([response("bad", usage=USAGE), response('{"ok": true}', usage=USAGE)])
    before = start()
    snapshot = (before.payload, before.request, before.responses, before.spend)
    runner(client).run(before)
    assert (before.payload, before.request, before.responses, before.spend) == snapshot


def test_a_request_for_another_model_is_refused() -> None:
    run: LlmRunner[str, Out] = LlmRunner(ScriptedLlmClient([]), spec("model-b"), Out)
    with pytest.raises(ValueError, match="runner is for"):
        run.run(start())


def test_cache_hits_are_counted_but_cost_nothing() -> None:
    cache = InMemoryCache()
    live = CachingLlmClient(ScriptedLlmClient([response(usage=USAGE)]), cache, CacheMode.READ_WRITE)
    _, first = runner(live).run(start())
    replay = CachingLlmClient(None, cache, CacheMode.READ_ONLY)
    out, second = runner(replay).run(start())
    assert out == Out(ok=True)
    assert first.spend.calls == 1
    assert second.spend.calls == 0
    assert second.spend.cache_hits == 1
    assert second.spend.cost == Decimal(0)
    assert second.spend.replayed_usage == USAGE


def test_unpriced_spec_gives_unknown_cost_not_zero() -> None:
    client = ScriptedLlmClient([response(usage=USAGE)])
    run: LlmRunner[str, Out] = LlmRunner(client, spec(price=None), Out)
    _, inv = run.run(start())
    assert inv.spend.cost is None


class Secretive(BaseModel):
    token: str

    @field_validator("token")
    @classmethod
    def _echo(cls, value: str) -> str:
        raise ValueError(f"rejected secret={value}")


def test_repair_and_error_never_echo_validator_messages_or_values() -> None:
    client = ScriptedLlmClient(
        [response('{"token": "TOPSECRET"}', usage=USAGE), response('{"token": "TOPSECRET2"}', usage=USAGE)]
    )
    with pytest.raises(LlmCallError) as caught:
        LlmRunner[str, Secretive](client, spec(), Secretive).run(start())
    fix = client.requests[1].messages[-1]
    assert fix.role == "user"
    assert "token [value_error]" in fix.content
    assert "TOPSECRET" not in fix.content
    assert "rejected" not in fix.content
    assert caught.value.validation == (("token", "value_error"),)


class SwitchModel(BaseRequestProcessor[str]):
    @override
    def process(self, invocation: Invocation[str]) -> Invocation[str]:
        other = ModelIdentity(provider=Provider.OLLAMA, deployment="other", model_version="v2")
        return replace(invocation, request=LlmRequest(model=other, messages=invocation.request.messages))


class ForgeSpend(BaseRequestProcessor[str]):
    @override
    def process(self, invocation: Invocation[str]) -> Invocation[str]:
        return replace(invocation, spend=Spend(calls=7))


class EraseSpend(BaseResponseProcessor[str, Out]):
    @override
    def process(self, invocation: Invocation[str], output: Out) -> Invocation[str]:
        return replace(invocation, spend=Spend(), responses=())


class RewriteRequest(BaseResponseProcessor[str, Out]):
    @override
    def process(self, invocation: Invocation[str], output: Out) -> Invocation[str]:
        return replace(invocation, request=request())


@pytest.mark.parametrize("processor", [SwitchModel(), ForgeSpend()], ids=["model", "spend"])
def test_a_request_processor_cannot_change_runner_owned_fields(processor: BaseRequestProcessor[str]) -> None:
    client = ScriptedLlmClient([response('{"ok": true}', usage=USAGE)])
    with pytest.raises(ProcessorContractError):
        LlmRunner[str, Out](client, spec(), Out, request_processors=[processor]).run(start())
    assert client.requests == []


@pytest.mark.parametrize("processor", [EraseSpend(), RewriteRequest()], ids=["spend", "request"])
def test_a_response_processor_may_change_only_the_payload(processor: BaseResponseProcessor[str, Out]) -> None:
    client = ScriptedLlmClient([response('{"ok": true}', usage=USAGE)])
    with pytest.raises(ProcessorContractError):
        LlmRunner[str, Out](client, spec(), Out, response_processors=[processor]).run(start())


class Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: int


class Nested(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[Inner]
    tags: dict[str, int]


def test_declared_names_cover_nested_models() -> None:
    assert declared_names(Nested.model_json_schema(mode="validation")) == {"items", "tags", "score"}


def test_locations_keep_declared_fields_and_indices_and_redact_model_invented_keys() -> None:
    bad = '{"items": [{"score": "x", "SECRETKEY": 1}], "tags": {"OTHERSECRET": "y"}, "INVENTED": 0}'
    client = ScriptedLlmClient([response(bad), response(bad)])
    with pytest.raises(LlmCallError) as raised:
        LlmRunner[str, Nested](client, spec(), Nested).run(start())
    text = str(raised.value) + client.requests[1].messages[-1].content  # [-2] echoes the reply by design
    for secret in ("SECRETKEY", "OTHERSECRET", "INVENTED"):
        assert secret not in text
    assert "items.0.score [int_parsing]" in text
    assert f"items.0.{UNDECLARED} [extra_forbidden]" in text
    assert f"tags.{UNDECLARED} [int_parsing]" in text
