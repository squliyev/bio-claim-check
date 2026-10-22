"""[RING:engine/llm] Content-addressed LLM cache: repeats are distinct calls, replay fails closed.

Why: the key covers every request-shaping input, including the model identity and `repeat_idx`, so three
repeats are three provider calls (review #1) and a re-pointed deployment misses (I43). Read-only replay
needs no provider at all (`inner=None`). The stored bytes are the response without `cache_hit` and
without billing fields; the returned response is always built from the stored bytes (first write wins,
ADR 0009), while the bill reflects what this run actually paid for.
Must not: import a provider driver, repair output, or store anything a run did not receive.
"""

from typing import override

from pydantic import ValidationError

from bio_claim_check.engine.cache.base_cache import BaseCache
from bio_claim_check.engine.cache.policy import CacheError, CacheMode, cache_key, fetch_through_result
from bio_claim_check.engine.llm.base_llm_client import BaseLlmClient
from bio_claim_check.engine.llm.messages import LlmRequest, LlmResponse

NAMESPACE = "llm.complete"
KEY_VERSION = 1
_NOT_STORED = frozenset({"cache_hit", "billed_usage"})


def llm_cache_key(request: LlmRequest) -> str:
    return cache_key(NAMESPACE, KEY_VERSION, request.cache_payload())


class CachingLlmClient(BaseLlmClient):
    """Wraps `inner` with the cache; `inner=None` is allowed only for read-only replay."""

    def __init__(self, inner: BaseLlmClient | None, cache: BaseCache, mode: CacheMode) -> None:
        if inner is None and mode is not CacheMode.READ_ONLY:
            raise ValueError(f"cache mode {mode} needs a live client; only read-only replay may omit it")
        self._inner = inner
        self._cache = cache
        self._mode = mode

    @override
    def complete(self, request: LlmRequest) -> LlmResponse:
        fetched = fetch_through_result(
            self._cache, self._mode, llm_cache_key(request), lambda: self._live(request), namespace=NAMESPACE
        )
        stored = _load(fetched.data)
        if fetched.live is None:
            return LlmResponse.model_validate({**stored.model_dump(), "cache_hit": True})
        live = _load(fetched.live)
        if live == stored:
            return stored
        return LlmResponse.model_validate({**stored.model_dump(), "billed_usage": live.usage.model_dump()})

    def _live(self, request: LlmRequest) -> bytes:
        if self._inner is None:  # unreachable: read-only never fetches; kept as a fail-closed check
            raise CacheError(f"{NAMESPACE}: no live client")
        response = self._inner.complete(request)
        return response.model_dump_json(exclude=set(_NOT_STORED)).encode("utf-8")


def _load(data: bytes) -> LlmResponse:
    try:
        response = LlmResponse.model_validate_json(data)
    except ValidationError as error:
        count = error.error_count()
        raise CacheError(f"{NAMESPACE}: stored entry is not a valid response ({count} error(s))") from error
    if response.cache_hit or response.billed_usage is not None:
        raise CacheError(f"{NAMESPACE}: stored entry carries per-run fields")
    return response
