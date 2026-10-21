"""[RING:engine/cache] A SQLite cache file: the replay store that survives the process (ADR 0009).

Why: one file under `var/` that a later run, CI or a reviewer can replay from. Writes use
`INSERT OR IGNORE`, so the first write wins even across processes; WAL lets a reader and a writer share
the file. Read-only opens the file with SQLite's `mode=ro` URI, so a replay cannot modify it, and a
missing file is a miss on every key (it is never created). Anything else that is not a usable SQLite file
(a directory, an unwritable folder, a corrupt file) is a `CacheError`, never a silent miss.
Must not: store timestamps or anything but the key and the bytes; set up schema on a read-only connection.
"""

import sqlite3
from pathlib import Path
from types import TracebackType
from typing import Self, override

from bio_claim_check.engine.cache.base_cache import BaseCache
from bio_claim_check.engine.cache.policy import CacheError

_SCHEMA = "CREATE TABLE IF NOT EXISTS entries (key TEXT PRIMARY KEY, data BLOB NOT NULL) WITHOUT ROWID"


class SqliteCache(BaseCache):
    """A cache backed by one SQLite file. Use as a context manager, or call `close()`."""

    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self._read_only = read_only
        self._conn: sqlite3.Connection | None = None
        try:
            resolved = path.resolve()
            if read_only:
                if resolved.exists():
                    if not resolved.is_file():
                        raise CacheError(f"the cache at {resolved} is not a file")
                    self._conn = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
            else:
                resolved.parent.mkdir(parents=True, exist_ok=True)
                self._conn = sqlite3.connect(resolved)
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute(_SCHEMA)
                self._conn.commit()
        except (sqlite3.Error, OSError) as exc:
            self.close()
            raise CacheError(f"cannot open the cache at {path}: {exc}") from exc

    @override
    def get(self, key: str) -> bytes | None:
        if self._conn is None:
            return None
        try:
            row = self._conn.execute("SELECT data FROM entries WHERE key = ?", (key,)).fetchone()
        except sqlite3.OperationalError as exc:
            if self._read_only and "no such table" in str(exc):
                return None  # a read-only file that was never written to
            raise CacheError(f"cannot read the cache: {exc}") from exc
        except sqlite3.Error as exc:
            raise CacheError(f"cannot read the cache: {exc}") from exc
        if row is None:
            return None
        data = row[0]
        if not isinstance(data, bytes):
            raise CacheError(f"corrupt cache entry {key[:12]}…: not bytes")
        return data

    @override
    def put(self, key: str, data: bytes) -> None:
        if self._read_only or self._conn is None:
            raise CacheError("the cache is read-only")
        try:
            with self._conn:
                self._conn.execute("INSERT OR IGNORE INTO entries (key, data) VALUES (?, ?)", (key, data))
        except sqlite3.Error as exc:
            raise CacheError(f"cannot write the cache: {exc}") from exc

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()
