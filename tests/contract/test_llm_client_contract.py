"""Shared LLM client contract (R6): every `BaseLlmClient` returns what the model produced, unaltered.

Case-based: each variant builds a client and the (request, expected response) cases it can serve. The
scripted and caching clients serve hand-built responses; each provider backend replays its success
fixtures (tests/fixtures/llm, recorded or labelled synthetic) through a mock transport, so the same
assertions hold for real providers without a network (I33, I56).
"""

from collections.abc import Callable, Sequence

import pytest

from bio_claim_check.engine.cache.in_memory_cache import InMemoryCache
from bio_claim_check.engine.cache.policy import CacheMode
from bio_claim_check.engine.llm.anthropic_llm_client import AnthropicLlmClient
from bio_claim_check.engine.llm.base_llm_client import BaseLlmClient
from bio_claim_check.engine.llm.budgeted_llm_client import BudgetedLlmClient, CallBudget
from bio_claim_check.engine.llm.caching_llm_client import CachingLlmClient
from bio_claim_check.engine.llm.messages import FinishReason, LlmRequest, LlmResponse
from bio_claim_check.engine.llm.openai_llm_client import OpenAiLlmClient
from bio_claim_check.engine.llm.scripted_llm_client import ScriptedLlmClient
from bio_claim_check.engine.llm.usage import Usage
from tests.support.llm import request, response
from tests.support.llm_fixtures import ProviderDir, ReplayTransport, backend, load_fixtures

pytestmark = pytest.mark.contract

IMPLEMENTATIONS: tuple[type[BaseLlmClient], ...] = (
    ScriptedLlmClient,
    BudgetedLlmClient,
    CachingLlmClient,
    OpenAiLlmClient,
    AnthropicLlmClient,
)
"""Must equal the discovered implementations (I33, enforced in tests/arch/test_port_guards.py)."""

type Case = tuple[LlmRequest, LlmResponse]
Factory = Callable[[], tuple[BaseLlmClient, Sequence[Case]]]

REQUESTS = tuple(request(repeat_idx=i) for i in range(3))
RESPONSES = (
    response('{"a": "  spaced ü \\n"}'),
    response("not json at all", finish=FinishReason.LENGTH, usage=Usage(input_tokens=7, output_tokens=3)),
    response('""', finish=FinishReason.CONTENT_FILTER, usage=Usage()),
)
HAND_BUILT: tuple[Case, ...] = tuple(zip(REQUESTS, RESPONSES, strict=True))


def _scripted() -> tuple[BaseLlmClient, Sequence[Case]]:
    return ScriptedLlmClient(RESPONSES), HAND_BUILT


def _caching() -> tuple[BaseLlmClient, Sequence[Case]]:
    return CachingLlmClient(ScriptedLlmClient(RESPONSES), InMemoryCache(), CacheMode.READ_WRITE), HAND_BUILT


def _budgeted() -> tuple[BaseLlmClient, Sequence[Case]]:
    return BudgetedLlmClient(ScriptedLlmClient(RESPONSES), CallBudget(len(RESPONSES))), HAND_BUILT


def _replay() -> tuple[BaseLlmClient, Sequence[Case]]:
    cache = InMemoryCache()
    recorder = CachingLlmClient(ScriptedLlmClient(RESPONSES), cache, CacheMode.READ_WRITE)
    for req in REQUESTS:
        recorder.complete(req)
    return CachingLlmClient(None, cache, CacheMode.READ_ONLY), HAND_BUILT


def _fixtures(provider: ProviderDir) -> Factory:
    def build() -> tuple[BaseLlmClient, Sequence[Case]]:
        fixtures = load_fixtures(provider, success_only=True)
        exchanges = tuple(e for f in fixtures for e in f.exchanges)
        cases = [(f.request, f.expected) for f in fixtures if f.expected is not None]
        return backend(provider, ReplayTransport(exchanges)), cases

    return build


_VARIANTS: dict[str, tuple[type[BaseLlmClient], Factory]] = {
    "scripted": (ScriptedLlmClient, _scripted),
    "budgeted": (BudgetedLlmClient, _budgeted),
    "caching-read-write": (CachingLlmClient, _caching),
    "caching-read-only-replay": (CachingLlmClient, _replay),
    "foundry-openai-fixtures": (OpenAiLlmClient, _fixtures("foundry_openai")),
    "foundry-anthropic-fixtures": (AnthropicLlmClient, _fixtures("foundry_anthropic")),
}


def test_every_implementation_has_a_variant() -> None:
    assert {cls for cls, _ in _VARIANTS.values()} == set(IMPLEMENTATIONS)


@pytest.fixture(params=sorted(_VARIANTS))
def variant(request: pytest.FixtureRequest) -> tuple[BaseLlmClient, Sequence[Case]]:
    _, factory = _VARIANTS[request.param]
    client, cases = factory()
    assert cases, f"variant {request.param} has no cases"
    return client, cases


def test_text_usage_and_finish_reason_are_returned_unaltered(
    variant: tuple[BaseLlmClient, Sequence[Case]],
) -> None:
    client, cases = variant
    got = [client.complete(req) for req, _ in cases]
    expected = [exp for _, exp in cases]
    assert [r.text for r in got] == [r.text for r in expected]
    assert [r.usage for r in got] == [r.usage for r in expected]
    assert [r.finish_reason for r in got] == [r.finish_reason for r in expected]
    assert [r.deployment for r in got] == [r.deployment for r in expected]


def test_paid_usage_is_never_more_than_one_call(variant: tuple[BaseLlmClient, Sequence[Case]]) -> None:
    client, cases = variant
    for req, expected in cases:
        got = client.complete(req)
        assert got.paid_usage in (None, expected.usage)
