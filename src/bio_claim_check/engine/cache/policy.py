"""[RING:engine/cache] Cache modes, keys and the one read-through rule every caller uses.

Why: the replay guarantee must not depend on each backend remembering the rules. One function decides
when to read, fetch and store, and `read-only` can never reach `fetch` (ADR 0009, invariant I32).
The key is the sha256 of canonical JSON over a namespace, a version and every request-shaping input,
so changing any of them misses instead of returning a stale answer (I34).
Must not: know what is cached, or read a clock.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from pydantic import JsonValue

from bio_claim_check.common.canonical_json import compact_sha256
from bio_claim_check.common.errors import BccError
from bio_claim_check.engine.cache.base_cache import BaseCache


class CacheMode(StrEnum):
    """How a run uses the cache."""

    READ_WRITE = "read-write"
    READ_ONLY = "read-only"
    OFF = "off"


class CacheError(BccError):
    """The cache itself failed (cannot open, cannot write)."""

    code = "cache.failed"


class CacheMissError(BccError, LookupError):
    """`read-only` mode and the key is absent: fail closed instead of fetching."""

    code = "cache.miss"

    def __init__(self, namespace: str) -> None:
        super().__init__(f"{namespace}: not in the cache and the cache mode is read-only")
        self.namespace = namespace


def cache_key(namespace: str, version: int, payload: Mapping[str, JsonValue]) -> str:
    """sha256 (hex) of canonical JSON over the namespace, its version and the request payload."""
    if not namespace.strip():
        raise ValueError("cache namespace must not be blank")
    body = {"namespace": namespace, "version": version, "payload": dict(payload)}
    return compact_sha256(body)


@dataclass(frozen=True, slots=True)
class Fetched:
    """What `fetch_through_result` returned, and whether this call paid for a live fetch.

    `data` is what the caller must use (the stored bytes, so every replay sees the same).
    `live` is what `fetch()` returned in this call, or None on a cache hit. They differ only when another
    writer stored the key first; spend is counted on `live`, the result is built from `data`.
    """

    data: bytes
    live: bytes | None


def fetch_through_result(
    cache: BaseCache, mode: CacheMode, key: str, fetch: Callable[[], bytes], *, namespace: str
) -> Fetched:
    """Return the bytes for `key`, and the live bytes if `fetch` ran.

    - `off`: always `fetch()`; the cache is neither read nor written.
    - `read-only`: the cached bytes, or `CacheMissError`; `fetch` is never called.
    - `read-write`: the cached bytes, else `fetch()` then store. `fetch` must raise on anything that
      should not be stored (an error status, a malformed body), so only good responses are frozen.
      The stored bytes are returned, not the fetched ones: if another process stored the key first,
      this run uses the bytes every replay will see.
    """
    if mode is CacheMode.OFF:
        live = fetch()
        return Fetched(data=live, live=live)
    if (hit := cache.get(key)) is not None:
        return Fetched(data=hit, live=None)
    if mode is CacheMode.READ_ONLY:
        raise CacheMissError(namespace)
    live = fetch()
    cache.put(key, live)
    stored = cache.get(key)
    if stored is None:
        raise CacheError(f"the {namespace} cache did not keep a written entry")
    return Fetched(data=stored, live=live)


def fetch_through(
    cache: BaseCache, mode: CacheMode, key: str, fetch: Callable[[], bytes], *, namespace: str
) -> bytes:
    """`fetch_through_result(...).data`, for callers that do not count spend."""
    return fetch_through_result(cache, mode, key, fetch, namespace=namespace).data
