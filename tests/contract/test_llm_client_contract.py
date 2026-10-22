"""Shared LLM client contract (R6): every `BaseLlmClient` returns what the model produced, unaltered."""

from collections.abc import Callable, Sequence

import pytest

from bio_claim_check.engine.cache.in_memory_cache import InMemoryCache
from bio_claim_check.engine.cache.policy import CacheMode
from bio_claim_check.engine.llm.base_llm_client import BaseLlmClient
from bio_claim_check.engine.llm.caching_llm_client import CachingLlmClient
from bio_claim_check.engine.llm.messages import FinishReason, LlmRequest, LlmResponse
from bio_claim_check.engine.llm.scripted_llm_client import ScriptedLlmClient
from bio_claim_check.engine.llm.usage import Usage
from tests.support.llm import request, response

pytestmark = pytest.mark.contract

IMPLEMENTATIONS: tuple[type[BaseLlmClient], ...] = (ScriptedLlmClient, CachingLlmClient)
"""Must equal the discovered implementations (I33, enforced in tests/arch/test_port_guards.py)."""

Factory = Callable[[Sequence[LlmRequest], Sequence[LlmResponse]], BaseLlmClient]


def _scripted(_: Sequence[LlmRequest], responses: Sequence[LlmResponse]) -> BaseLlmClient:
    return ScriptedLlmClient(responses)


def _caching(_: Sequence[LlmRequest], responses: Sequence[LlmResponse]) -> BaseLlmClient:
    return CachingLlmClient(ScriptedLlmClient(responses), InMemoryCache(), CacheMode.READ_WRITE)


def _replay(requests: Sequence[LlmRequest], responses: Sequence[LlmResponse]) -> BaseLlmClient:
    cache = InMemoryCache()
    recorder = CachingLlmClient(ScriptedLlmClient(responses), cache, CacheMode.READ_WRITE)
    for req in requests:
        recorder.complete(req)
    return CachingLlmClient(None, cache, CacheMode.READ_ONLY)


_VARIANTS: dict[str, tuple[type[BaseLlmClient], Factory]] = {
    "scripted": (ScriptedLlmClient, _scripted),
    "caching-read-write": (CachingLlmClient, _caching),
    "caching-read-only-replay": (CachingLlmClient, _replay),
}

REQUESTS = tuple(request(repeat_idx=i) for i in range(3))
RESPONSES = (
    response('{"a": "  spaced ü \\n"}'),
    response("not json at all", finish=FinishReason.LENGTH, usage=Usage(input_tokens=7, output_tokens=3)),
    response('""', finish=FinishReason.CONTENT_FILTER, usage=Usage()),
)


def test_every_implementation_has_a_variant() -> None:
    assert {cls for cls, _ in _VARIANTS.values()} == set(IMPLEMENTATIONS)


@pytest.fixture(params=sorted(_VARIANTS))
def client(request: pytest.FixtureRequest) -> BaseLlmClient:
    _, factory = _VARIANTS[request.param]
    return factory(REQUESTS, RESPONSES)


def test_text_usage_and_finish_reason_are_returned_unaltered(client: BaseLlmClient) -> None:
    got = [client.complete(req) for req in REQUESTS]
    assert [r.text for r in got] == [r.text for r in RESPONSES]
    assert [r.usage for r in got] == [r.usage for r in RESPONSES]
    assert [r.finish_reason for r in got] == [r.finish_reason for r in RESPONSES]
    assert [r.deployment for r in got] == [r.deployment for r in RESPONSES]


def test_paid_usage_is_never_more_than_one_call(client: BaseLlmClient) -> None:
    for req, expected in zip(REQUESTS, RESPONSES, strict=True):
        got = client.complete(req)
        assert got.paid_usage in (None, expected.usage)
