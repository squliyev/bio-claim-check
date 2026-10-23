"""[RING:infrastructure] Line-oriented files: a new file written line by line, and append-only lines.

Why: a run's trace must survive a crash up to its last line, and the run ledger must only ever grow
(ADR 0018). `create_numbered` opens `<stem>-<n><suffix>` with exclusive create, trying n = 0, 1, ... so
two commands started in the same second never share or replace a file. `LineFile.write_line` writes and
flushes each line; `close` fsyncs. `append_line` writes a whole line with `O_APPEND`, retrying partial
writes, and fsyncs; if a write fails it truncates the file back to where it started, so a later row is
never glued to a fragment. The guarantees hold for one writer process and for process crashes; locking
and power-loss durability (directory fsync) are out of scope.
Must not: know what the lines mean, overwrite an existing file, or accept data containing a newline.

No LLM is involved in this module.
"""

import errno
import os
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Self

from bio_claim_check.common.errors import BccError

NEWLINE = b"\n"


class AppendError(BccError):
    """A line could not be appended (the file is unchanged), or the data is not one line."""

    code = "files.append"


def _check_line(data: bytes) -> None:
    if NEWLINE in data or b"\r" in data:
        raise AppendError("a line must not contain a newline")


class LineFile:
    """A newly created file that receives whole lines; use as a context manager."""

    def __init__(self, path: Path, handle: BinaryIO) -> None:
        self.path = path
        self._handle = handle

    def write_line(self, data: bytes) -> None:
        _check_line(data)
        self._handle.write(data + NEWLINE)
        self._handle.flush()

    def close(self) -> None:
        if self._handle.closed:
            return
        try:
            self._handle.flush()
            os.fsync(self._handle.fileno())
        finally:
            self._handle.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()


def create_numbered(folder: Path, stem: str, suffix: str, *, limit: int = 100) -> LineFile:
    """Create `folder/<stem>-<n><suffix>` for the first free n < `limit`; `FileExistsError` if none is."""
    folder.mkdir(parents=True, exist_ok=True)
    for n in range(limit):
        path = folder / f"{stem}-{n}{suffix}"
        try:
            handle = path.open("xb")
        except FileExistsError:
            continue
        return LineFile(path, handle)
    raise FileExistsError(f"{folder}/{stem}-0..{limit - 1}{suffix} are all taken")


def append_line(path: Path, data: bytes) -> None:
    """Append `data` and a newline to `path` (created if absent); on failure the file is left as it was.

    Every `OSError` (open, size, write, fsync, close) becomes one `AppendError`; the first one wins, and
    the message says so if the partial line could not be truncated away.
    """
    _check_line(data)
    line = data + NEWLINE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    except OSError as err:
        raise AppendError(f"cannot open {path}: {err.strerror or err}") from err
    failure: OSError | None = None
    rolled_back = True
    try:
        start = os.fstat(fd).st_size
        try:
            _write_all(fd, line)
            os.fsync(fd)
        except OSError as err:
            failure = err
            rolled_back = _truncate(fd, start)
    except OSError as err:
        failure = err
    finally:
        try:
            os.close(fd)
        except OSError as err:
            failure = failure or err
    if failure is not None:
        left = "" if rolled_back else "; the partial line could not be removed"
        raise AppendError(f"cannot append to {path}: {failure.strerror or failure}{left}") from failure


def _write_all(fd: int, line: bytes) -> None:
    written = 0
    while written < len(line):
        n = os.write(fd, line[written:])
        if n <= 0:
            raise OSError(errno.EIO, "a write made no progress")
        written += n


def _truncate(fd: int, size: int) -> bool:
    try:
        os.ftruncate(fd, size)
    except OSError:
        return False
    return True
