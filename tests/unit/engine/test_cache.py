"""Cache policy and the SQLite backend specifics (the shared behaviour is in tests/contract)."""

import sqlite3
from pathlib import Path
from typing import override

import pytest

from bio_claim_check.engine.cache.in_memory_cache import InMemoryCache
from bio_claim_check.engine.cache.policy import (
    CacheError,
    CacheMissError,
    CacheMode,
    Fetched,
    cache_key,
    fetch_through,
    fetch_through_result,
)
from bio_claim_check.engine.cache.sqlite_cache import SqliteCache

pytestmark = pytest.mark.unit


class _Fetch:
    def __init__(self, data: bytes = b"fresh") -> None:
        self.calls = 0
        self.data = data

    def __call__(self) -> bytes:
        self.calls += 1
        return self.data


def test_key_is_stable_and_order_independent() -> None:
    a = cache_key("ns", 1, {"q": "x", "k": 5})
    assert a == cache_key("ns", 1, {"k": 5, "q": "x"})
    assert len(a) == 64


@pytest.mark.parametrize(
    "other",
    [("ns2", 1, {"q": "x", "k": 5}), ("ns", 2, {"q": "x", "k": 5}), ("ns", 1, {"q": "x", "k": 6})],
)
def test_every_input_changes_the_key(other: tuple[str, int, dict[str, str | int]]) -> None:
    assert cache_key(*other) != cache_key("ns", 1, {"q": "x", "k": 5})


def test_key_rejects_a_blank_namespace_and_nan() -> None:
    with pytest.raises(ValueError, match="namespace"):
        cache_key(" ", 1, {})
    with pytest.raises(ValueError, match="JSON"):
        cache_key("ns", 1, {"x": float("nan")})


def test_read_write_fetches_once_then_replays() -> None:
    cache, fetch = InMemoryCache(), _Fetch()
    assert fetch_through(cache, CacheMode.READ_WRITE, "k", fetch, namespace="ns") == b"fresh"
    fetch.data = b"changed"
    assert fetch_through(cache, CacheMode.READ_WRITE, "k", fetch, namespace="ns") == b"fresh"
    assert fetch.calls == 1


def test_read_only_never_fetches() -> None:
    cache, fetch = InMemoryCache(), _Fetch()
    with pytest.raises(CacheMissError, match="ns: not in the cache"):
        fetch_through(cache, CacheMode.READ_ONLY, "k", fetch, namespace="ns")
    cache.put("k", b"stored")
    assert fetch_through(cache, CacheMode.READ_ONLY, "k", fetch, namespace="ns") == b"stored"
    assert fetch.calls == 0


def test_off_neither_reads_nor_writes() -> None:
    cache, fetch = InMemoryCache(), _Fetch()
    cache.put("k", b"stored")
    assert fetch_through(cache, CacheMode.OFF, "k", fetch, namespace="ns") == b"fresh"
    assert fetch_through(cache, CacheMode.OFF, "j", fetch, namespace="ns") == b"fresh"
    assert cache.get("j") is None
    assert fetch.calls == 2


def test_a_failed_fetch_stores_nothing() -> None:
    cache = InMemoryCache()

    def boom() -> bytes:
        raise RuntimeError("upstream")

    with pytest.raises(RuntimeError):
        fetch_through(cache, CacheMode.READ_WRITE, "k", boom, namespace="ns")
    assert cache.get("k") is None


def test_a_concurrent_first_writer_wins_for_this_run_too() -> None:
    cache = InMemoryCache()

    def fetch_while_another_process_stores() -> bytes:
        cache.put("k", b"theirs")
        return b"ours"

    assert fetch_through(
        cache, CacheMode.READ_WRITE, "k", fetch_while_another_process_stores, namespace="ns"
    ) == (b"theirs")


class _SpyCache(InMemoryCache):
    def __init__(self) -> None:
        super().__init__()
        self.touched = 0

    @override
    def get(self, key: str) -> bytes | None:
        self.touched += 1
        return super().get(key)

    @override
    def put(self, key: str, data: bytes) -> None:
        self.touched += 1
        super().put(key, data)


def test_result_reports_live_bytes_only_when_fetch_ran() -> None:
    cache = InMemoryCache()
    first = fetch_through_result(cache, CacheMode.READ_WRITE, "k", _Fetch(), namespace="ns")
    assert first == Fetched(data=b"fresh", live=b"fresh")
    again = fetch_through_result(cache, CacheMode.READ_WRITE, "k", _Fetch(b"other"), namespace="ns")
    assert again == Fetched(data=b"fresh", live=None)
    replay = fetch_through_result(cache, CacheMode.READ_ONLY, "k", _Fetch(), namespace="ns")
    assert replay == Fetched(data=b"fresh", live=None)


def test_result_on_a_lost_race_uses_stored_bytes_but_reports_the_paid_fetch() -> None:
    cache = InMemoryCache()

    def fetch_while_another_process_stores() -> bytes:
        cache.put("k", b"theirs")
        return b"ours"

    got = fetch_through_result(
        cache, CacheMode.READ_WRITE, "k", fetch_while_another_process_stores, namespace="ns"
    )
    assert got == Fetched(data=b"theirs", live=b"ours")


def test_result_in_off_mode_never_touches_the_cache() -> None:
    cache = _SpyCache()
    got = fetch_through_result(cache, CacheMode.OFF, "k", _Fetch(), namespace="ns")
    assert got == Fetched(data=b"fresh", live=b"fresh")
    assert cache.touched == 0


class _ForgetfulCache(InMemoryCache):
    @override
    def get(self, key: str) -> bytes | None:
        return None


def test_a_cache_that_drops_writes_is_an_error() -> None:
    with pytest.raises(CacheError, match="did not keep"):
        fetch_through(_ForgetfulCache(), CacheMode.READ_WRITE, "k", _Fetch(), namespace="ns")


def test_sqlite_survives_reopening_and_first_write_wins(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "cache.sqlite"
    with SqliteCache(path) as cache:
        cache.put("k", b"one")
    with SqliteCache(path) as cache:
        cache.put("k", b"two")
        assert cache.get("k") == b"one"
    with SqliteCache(path, read_only=True) as cache:
        assert cache.get("k") == b"one"


def test_sqlite_read_only_on_a_missing_file_misses_and_creates_nothing(tmp_path: Path) -> None:
    path = tmp_path / "absent.sqlite"
    with SqliteCache(path, read_only=True) as cache:
        assert cache.get("k") is None
        with pytest.raises(CacheError, match="read-only"):
            cache.put("k", b"x")
    assert not path.exists()


def test_sqlite_read_only_cannot_write_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "c.sqlite"
    SqliteCache(path).close()
    with SqliteCache(path, read_only=True) as cache, pytest.raises(CacheError, match="read-only"):
        cache.put("k", b"x")


def test_sqlite_read_only_on_an_empty_database_misses(tmp_path: Path) -> None:
    path = tmp_path / "empty.sqlite"
    sqlite3.connect(path).close()
    path.touch()
    with SqliteCache(path, read_only=True) as cache:
        assert cache.get("k") is None


def test_sqlite_garbage_file_is_a_cache_error(tmp_path: Path) -> None:
    path = tmp_path / "junk.sqlite"
    path.write_bytes(b"this is not a database" * 100)
    with pytest.raises(CacheError, match="cannot"):
        SqliteCache(path)


def test_sqlite_read_only_on_a_directory_is_a_cache_error(tmp_path: Path) -> None:
    (tmp_path / "c.sqlite").mkdir()
    with pytest.raises(CacheError, match="not a file"):
        SqliteCache(tmp_path / "c.sqlite", read_only=True)


def test_sqlite_folder_that_cannot_be_created_is_a_cache_error(tmp_path: Path) -> None:
    (tmp_path / "var").write_text("a file where the folder should be")
    with pytest.raises(CacheError, match="cannot open"):
        SqliteCache(tmp_path / "var" / "cache.sqlite")
