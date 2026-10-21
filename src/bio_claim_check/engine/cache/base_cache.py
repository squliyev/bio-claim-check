"""[RING:engine/cache] The cache port: bytes in, bytes out, first write wins.

Why: replay is only honest if a key always returns the bytes the first run saw. "First write wins"
freezes a response (and so a search ranking) the moment it is stored (ADR 0009).
Must not: hold an implementation, expire entries, or record when something was stored (no clock in core).
"""

from abc import ABC, abstractmethod


class BaseCache(ABC):
    """A key → bytes store where a stored value never changes."""

    @abstractmethod
    def get(self, key: str) -> bytes | None:
        """Return the bytes stored under `key`, or None if there are none."""

    @abstractmethod
    def put(self, key: str, data: bytes) -> None:
        """Store `data` under `key` unless the key is already present; then do nothing (first write wins).

        Raises:
            CacheError: the cache cannot be written (e.g. opened read-only).
        """
