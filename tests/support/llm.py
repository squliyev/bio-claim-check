"""[TEST SUPPORT] Builders for LLM requests, responses and specs (engine/llm tests and contract suite)."""

from datetime import date
from decimal import Decimal

from bio_claim_check.engine.llm.messages import FinishReason, LlmRequest, LlmResponse, Message
from bio_claim_check.engine.llm.model_spec import ModelIdentity, ModelSpec, Provider
from bio_claim_check.engine.llm.usage import Price, Usage

IDENTITY = ModelIdentity(provider=Provider.FOUNDRY_OPENAI, deployment="model-a", model_version="model-a-v1")
PRICE = Price(
    input_per_mtok=Decimal("2.50"),
    output_per_mtok=Decimal("10"),
    cached_input_per_mtok=Decimal("1.25"),
    as_of=date(2026, 1, 1),
    source="test price sheet",
)


def user(text: str = "Is it supported?") -> Message:
    return Message(role="user", content=text)


def request(text: str = "Is it supported?", *, repeat_idx: int = 0) -> LlmRequest:
    return LlmRequest(model=IDENTITY, messages=(user(text),), repeat_idx=repeat_idx)


def response(
    text: str = '{"ok": true}',
    *,
    finish: FinishReason = FinishReason.STOP,
    usage: Usage | None = None,
) -> LlmResponse:
    return LlmResponse(
        text=text,
        usage=usage or Usage(input_tokens=100, output_tokens=20, reasoning_tokens=5),
        finish_reason=finish,
        deployment=IDENTITY.deployment,
    )


def spec(deployment: str = "model-a", *, price: Price | None = PRICE) -> ModelSpec:
    return ModelSpec(
        deployment=deployment,
        provider=Provider.FOUNDRY_OPENAI,
        model_version=f"{deployment}-v1",
        params={"temperature": 0, "nested": {"top_p": 1}},
        price=price,
    )
