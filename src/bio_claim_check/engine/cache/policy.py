"""[RING:engine/cache] Cache modes, keys and the one read-through rule every caller uses.

Why: the replay guarantee must not depend on each backend remembering the rules. One function decides
when to read, fetch and store, and `read-only` can never reach `fetch` (ADR 0009, invariant I32).
The key is the sha256 of canonical JSON over a namespace, a version and every request-shaping input,
so changing any of them misses instead of returning a stale answer (I34).
Must not: know what is cached, or read a clock.
"""

import hashlib
import json
from collections.abc import Callable, Mapping
from enum import StrEnum

from pydantic import JsonValue

from bio_claim_check.engine.cache.base_cache import BaseCache


class CacheMode(StrEnum):
    """How a run uses the cache."""

    READ_WRITE = "read-write"
    READ_ONLY = "read-only"
    OFF = "off"


class CacheError(Exception):
    """The cache itself failed (cannot open, cannot write)."""


class CacheMissError(LookupError):
    """`read-only` mode and the key is absent: fail closed instead of fetching."""

    def __init__(self, namespace: str) -> None:
        super().__init__(f"{namespace}: not in the cache and the cache mode is read-only")
        self.namespace = namespace


def cache_key(namespace: str, version: int, payload: Mapping[str, JsonValue]) -> str:
    """sha256 (hex) of canonical JSON over the namespace, its version and the request payload."""
    if not namespace.strip():
        raise ValueError("cache namespace must not be blank")
    body = {"namespace": namespace, "version": version, "payload": dict(payload)}
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fetch_through(
    cache: BaseCache, mode: CacheMode, key: str, fetch: Callable[[], bytes], *, namespace: str
) -> bytes:
    """Return the bytes for `key`.

    - `off`: always `fetch()`; the cache is neither read nor written.
    - `read-only`: the cached bytes, or `CacheMissError`; `fetch` is never called.
    - `read-write`: the cached bytes, else `fetch()` then store. `fetch` must raise on anything that
      should not be stored (an error status, a malformed body), so only good responses are frozen.
      The stored bytes are returned, not the fetched ones: if another process stored the key first,
      this run uses the bytes every replay will see.
    """
    if mode is CacheMode.OFF:
        return fetch()
    if (hit := cache.get(key)) is not None:
        return hit
    if mode is CacheMode.READ_ONLY:
        raise CacheMissError(namespace)
    cache.put(key, fetch())
    stored = cache.get(key)
    if stored is None:
        raise CacheError(f"the {namespace} cache did not keep a written entry")
    return stored
