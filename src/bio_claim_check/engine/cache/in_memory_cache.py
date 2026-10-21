"""[RING:engine/cache] An in-memory cache (tests, contract suite, short-lived processes).

Why: the simplest real implementation of the cache contract; it runs the shared contract suite.
Must not: be used where a replay must survive the process.
"""

from typing import override

from bio_claim_check.engine.cache.base_cache import BaseCache


class InMemoryCache(BaseCache):
    """A dict that never overwrites."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    @override
    def get(self, key: str) -> bytes | None:
        return self._data.get(key)

    @override
    def put(self, key: str, data: bytes) -> None:
        self._data.setdefault(key, bytes(data))
