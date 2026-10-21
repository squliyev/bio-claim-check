"""Shared cache contract (ADR 0009): every `BaseCache` implementation passes the same scenarios."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from bio_claim_check.engine.cache.base_cache import BaseCache
from bio_claim_check.engine.cache.in_memory_cache import InMemoryCache
from bio_claim_check.engine.cache.sqlite_cache import SqliteCache

pytestmark = pytest.mark.contract

IMPLEMENTATIONS: tuple[type[BaseCache], ...] = (InMemoryCache, SqliteCache)
"""Must equal the discovered implementations (I33, enforced in tests/arch/test_port_guards.py)."""

_FACTORIES: dict[type[BaseCache], Callable[[Path], BaseCache]] = {
    InMemoryCache: lambda _: InMemoryCache(),
    SqliteCache: lambda tmp: SqliteCache(tmp / "dir with spaces & ü" / "cache.sqlite"),
}


@pytest.fixture(params=IMPLEMENTATIONS, ids=lambda c: c.__name__)
def cache(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[BaseCache]:
    made = _FACTORIES[request.param](tmp_path)
    yield made
    if isinstance(made, SqliteCache):
        made.close()


def test_a_missing_key_is_none(cache: BaseCache) -> None:
    assert cache.get("absent") is None


@pytest.mark.parametrize("data", [b"", b"\x00\xff binary", "ünïcode".encode(), b"x" * 1_000_000])
def test_round_trip(cache: BaseCache, data: bytes) -> None:
    cache.put("k", data)
    assert cache.get("k") == data


def test_first_write_wins(cache: BaseCache) -> None:
    cache.put("k", b"first")
    cache.put("k", b"second")
    assert cache.get("k") == b"first"


def test_keys_are_independent(cache: BaseCache) -> None:
    cache.put("a", b"1")
    cache.put("b", b"2")
    assert (cache.get("a"), cache.get("b"), cache.get("c")) == (b"1", b"2", None)


def test_stored_bytes_cannot_be_mutated_through_the_caller(cache: BaseCache) -> None:
    data = bytearray(b"orig")
    cache.put("k", bytes(data))
    data[0:4] = b"edit"
    assert cache.get("k") == b"orig"
