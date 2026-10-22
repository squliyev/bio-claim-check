"""Cache key coverage (I43), repeats, replay without a provider, honest billing on a lost race."""

from collections.abc import Callable
from typing import override

import pytest
from tests.support.llm import IDENTITY, request, response, user

from bio_claim_check.engine.cache.in_memory_cache import InMemoryCache
from bio_claim_check.engine.cache.policy import CacheError, CacheMissError, CacheMode
from bio_claim_check.engine.llm.caching_llm_client import CachingLlmClient, llm_cache_key
from bio_claim_check.engine.llm.messages import LlmRequest, LlmResponse, PromptRef
from bio_claim_check.engine.llm.model_spec import Provider
from bio_claim_check.engine.llm.scripted_llm_client import ScriptedLlmClient
from bio_claim_check.engine.llm.usage import Usage

pytestmark = pytest.mark.unit

BASE = request()


def _with(req: LlmRequest, **fields: object) -> LlmRequest:
    return LlmRequest.model_validate({**req.model_dump(), **fields})


def _model(**fields: object) -> dict[str, object]:
    return {**IDENTITY.model_dump(), **fields}


CHANGES: dict[str, Callable[[LlmRequest], LlmRequest]] = {
    "provider": lambda r: _with(r, model=_model(provider=Provider.OLLAMA)),
    "deployment": lambda r: _with(r, model=_model(deployment="model-b")),
    "model_version": lambda r: _with(r, model=_model(model_version="v2")),
    "params": lambda r: _with(r, params={"temperature": 0}),
    "nested_params": lambda r: _with(_with(r, params={"x": {"y": 1}}), params={"x": {"y": 2}}),
    "messages": lambda r: r.with_messages((user("Something else?"),)),
    "response_schema": lambda r: r.with_schema("Out", {"type": "object"}),
    "schema_name": lambda r: r.with_schema("Out", {}).with_schema("Other", {}),
    "seed": lambda r: _with(r, seed=1),
    "repeat_idx": lambda r: _with(r, repeat_idx=1),
}


@pytest.mark.parametrize("field", CHANGES)
def test_every_request_shaping_field_changes_the_key(field: str) -> None:
    changed = CHANGES[field](BASE)
    before = BASE if field not in {"nested_params", "schema_name"} else _baseline(field)
    assert llm_cache_key(changed) != llm_cache_key(before)


def _baseline(field: str) -> LlmRequest:
    return _with(BASE, params={"x": {"y": 1}}) if field == "nested_params" else BASE.with_schema("Out", {})


def test_the_prompt_reference_does_not_change_the_key() -> None:
    ref = PromptRef(name="verify", version=3, sha256="b" * 64)
    assert llm_cache_key(_with(BASE, prompt=ref)) == llm_cache_key(BASE)


def test_param_order_does_not_change_the_key() -> None:
    a = _with(BASE, params={"a": 1, "b": 2})
    b = _with(BASE, params={"b": 2, "a": 1})
    assert llm_cache_key(a) == llm_cache_key(b)


def test_repeats_are_distinct_provider_calls_and_replay_makes_none() -> None:
    cache = InMemoryCache()
    inner = ScriptedLlmClient([response(f'"{i}"') for i in range(3)])
    live = CachingLlmClient(inner, cache, CacheMode.READ_WRITE)
    first = [live.complete(request(repeat_idx=i)).text for i in range(3)]
    assert first == ['"0"', '"1"', '"2"']
    assert len(inner.requests) == 3

    replay = CachingLlmClient(None, cache, CacheMode.READ_ONLY)
    again = [replay.complete(request(repeat_idx=i)) for i in range(3)]
    assert [r.text for r in again] == first
    assert all(r.cache_hit and r.paid_usage is None for r in again)
    assert len(inner.requests) == 3


def test_read_only_miss_fails_closed() -> None:
    with pytest.raises(CacheMissError):
        CachingLlmClient(None, InMemoryCache(), CacheMode.READ_ONLY).complete(BASE)


@pytest.mark.parametrize("mode", [CacheMode.READ_WRITE, CacheMode.OFF])
def test_only_read_only_may_omit_the_live_client(mode: CacheMode) -> None:
    with pytest.raises(ValueError, match=r"needs a live client"):
        CachingLlmClient(None, InMemoryCache(), mode)


class _SpyCache(InMemoryCache):
    def __init__(self) -> None:
        super().__init__()
        self.gets = 0
        self.puts = 0

    @override
    def get(self, key: str) -> bytes | None:
        self.gets += 1
        return super().get(key)

    @override
    def put(self, key: str, data: bytes) -> None:
        self.puts += 1
        super().put(key, data)


def test_off_mode_neither_reads_nor_writes() -> None:
    cache = _SpyCache()
    inner = ScriptedLlmClient([response(), response()])
    client = CachingLlmClient(inner, cache, CacheMode.OFF)
    results = [client.complete(BASE), client.complete(BASE)]
    assert (cache.gets, cache.puts, len(inner.requests)) == (0, 0, 2)
    assert all(not r.cache_hit and r.paid_usage == r.usage for r in results)


def test_stored_bytes_carry_no_per_run_fields() -> None:
    cache = InMemoryCache()
    CachingLlmClient(ScriptedLlmClient([response()]), cache, CacheMode.READ_WRITE).complete(BASE)
    stored = cache.get(llm_cache_key(BASE))
    assert stored is not None
    assert b"cache_hit" not in stored
    assert b"billed_usage" not in stored


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"not json", r"not a valid response"),
        (b'{"text": "x"}', r"not a valid response"),
        (
            response()
            .model_copy(update=None)
            .model_dump_json()
            .replace('"cache_hit":false', '"cache_hit":true')
            .encode(),
            r"per-run fields",
        ),
    ],
)
def test_corrupt_stored_entries_raise_without_calling_the_provider(data: bytes, message: str) -> None:
    cache = InMemoryCache()
    cache.put(llm_cache_key(BASE), data)
    inner = ScriptedLlmClient([response()])
    with pytest.raises(CacheError, match=message):
        CachingLlmClient(inner, cache, CacheMode.READ_WRITE).complete(BASE)
    assert inner.requests == []


class _RacingCache(InMemoryCache):
    """Another writer stores its answer between our miss and our put (first write wins)."""

    def __init__(self, theirs: bytes) -> None:
        super().__init__()
        self._theirs = theirs
        self._raced = False

    @override
    def put(self, key: str, data: bytes) -> None:
        if not self._raced:
            self._raced = True
            super().put(key, self._theirs)
        super().put(key, data)


def test_a_lost_race_returns_their_text_and_bills_our_usage() -> None:
    ours = response('"ours"', usage=Usage(input_tokens=9, output_tokens=9))
    theirs = response('"theirs"', usage=Usage(input_tokens=1, output_tokens=1))
    cache = _RacingCache(theirs.model_dump_json(exclude={"cache_hit", "billed_usage"}).encode())
    result = CachingLlmClient(ScriptedLlmClient([ours]), cache, CacheMode.READ_WRITE).complete(BASE)
    assert result.text == '"theirs"'
    assert result.usage == theirs.usage
    assert result.paid_usage == ours.usage
    assert not result.cache_hit


def test_a_won_write_returns_the_live_response_as_paid() -> None:
    result = CachingLlmClient(
        ScriptedLlmClient([response()]), InMemoryCache(), CacheMode.READ_WRITE
    ).complete(BASE)
    assert result == response()
    assert result.paid_usage == response().usage


def test_scripted_client_records_requests_and_fails_when_exhausted() -> None:
    client = ScriptedLlmClient([response()])
    assert client.complete(BASE) == response()
    with pytest.raises(LookupError, match=r"only 1 response"):
        client.complete(BASE)
    assert client.requests == [BASE]


def test_responses_round_trip_through_json() -> None:
    assert LlmResponse.model_validate_json(response().model_dump_json()) == response()
