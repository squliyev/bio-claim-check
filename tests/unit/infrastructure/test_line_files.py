"""Line files (ADR 0018): numbered traces never replace a file; ledger appends never leave a fragment."""

import os
from pathlib import Path

import pytest

from bio_claim_check.infrastructure import line_files
from bio_claim_check.infrastructure.line_files import AppendError, append_line, create_numbered

pytestmark = pytest.mark.unit


def test_numbered_files_take_the_first_free_number_and_fail_closed_after_the_limit(tmp_path: Path) -> None:
    with create_numbered(tmp_path / "events", "s", ".jsonl", limit=2) as first:
        first.write_line(b"one")
        first.write_line(b"two")
    with create_numbered(tmp_path / "events", "s", ".jsonl", limit=2) as second:
        pass
    assert (first.path.name, second.path.name) == ("s-0.jsonl", "s-1.jsonl")
    assert first.path.read_bytes() == b"one\ntwo\n"
    with pytest.raises(FileExistsError):
        create_numbered(tmp_path / "events", "s", ".jsonl", limit=2)


@pytest.mark.parametrize("data", [b"a\nb", b"a\rb"])
def test_a_line_with_a_newline_is_refused(tmp_path: Path, data: bytes) -> None:
    with pytest.raises(AppendError):
        append_line(tmp_path / "ledger.jsonl", data)
    with create_numbered(tmp_path, "s", ".jsonl") as file, pytest.raises(AppendError):
        file.write_line(data)
    assert not (tmp_path / "ledger.jsonl").exists()


def test_appends_add_whole_lines(tmp_path: Path) -> None:
    path = tmp_path / "var" / "ledger.jsonl"
    append_line(path, b'{"n":1}')
    append_line(path, b'{"n":2}')
    assert path.read_bytes() == b'{"n":1}\n{"n":2}\n'


def test_a_failed_append_truncates_back_so_the_next_row_parses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ledger.jsonl"
    append_line(path, b"first")
    real_write = os.write

    def short_then_fail(fd: int, data: bytes) -> int:
        monkeypatch.setattr(line_files.os, "write", failing)
        return real_write(fd, data[:3])

    def failing(fd: int, data: bytes) -> int:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(line_files.os, "write", short_then_fail)
    with pytest.raises(AppendError, match="No space left"):
        append_line(path, b"second")
    monkeypatch.setattr(line_files.os, "write", real_write)
    append_line(path, b"third")
    assert path.read_bytes() == b"first\nthird\n"


def test_short_writes_are_retried_until_the_whole_line_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = os.write

    def two_bytes(fd: int, data: bytes) -> int:
        return real_write(fd, data[:2])

    monkeypatch.setattr(line_files.os, "write", two_bytes)
    append_line(tmp_path / "ledger.jsonl", b"abcdefg")
    assert (tmp_path / "ledger.jsonl").read_bytes() == b"abcdefg\n"


def _no_space(*_: object) -> None:
    raise OSError(28, "No space left on device")


def test_a_rollback_that_fails_is_still_one_append_error_that_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(line_files.os, "fsync", _no_space)
    monkeypatch.setattr(line_files.os, "ftruncate", _no_space)
    with pytest.raises(AppendError, match=r"No space left.*could not be removed"):
        append_line(path, b"row")


def test_a_close_failure_is_an_append_error_but_never_replaces_the_first_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ledger.jsonl"
    real_close = os.close

    def close_then_fail(fd: int) -> None:
        real_close(fd)
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(line_files.os, "close", close_then_fail)
    with pytest.raises(AppendError, match="Input/output error"):
        append_line(path, b"row")
    monkeypatch.setattr(line_files.os, "fsync", _no_space)
    with pytest.raises(AppendError, match="No space left"):
        append_line(path, b"row")


def test_a_write_that_makes_no_progress_fails_instead_of_spinning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ledger.jsonl"

    def no_progress(fd: int, data: bytes) -> int:
        del fd, data
        return 0

    monkeypatch.setattr(line_files.os, "write", no_progress)
    with pytest.raises(AppendError, match="no progress"):
        append_line(path, b"row")
    assert path.read_bytes() == b""
