"""Publish once: no-clobber, fsynced, never half-written, never outside its folder (S05, S05b)."""

from pathlib import Path

import pytest

from bio_claim_check.infrastructure import publish
from bio_claim_check.infrastructure.publish import PublishError, publish_once

pytestmark = pytest.mark.unit

DATA = b'{"a": 1}\n'


def test_write_is_idempotent(tmp_path: Path) -> None:
    first = publish_once(tmp_path / "run", "report.json", DATA)
    stamp = first.stat().st_mtime_ns
    assert publish_once(tmp_path / "run", "report.json", DATA) == first == tmp_path / "run" / "report.json"
    assert first.read_bytes() == DATA
    assert first.stat().st_mtime_ns == stamp
    assert [p.name for p in first.parent.iterdir()] == ["report.json"]


def test_refuses_to_overwrite_different_bytes(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    target.write_bytes(b"{}\n")
    with pytest.raises(PublishError, match="refusing to overwrite"):
        publish_once(tmp_path, "report.json", DATA)
    assert target.read_bytes() == b"{}\n"


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "../x", "a\\b", "/abs", "a\0b"])
def test_only_plain_file_names_are_accepted_and_nothing_is_created(tmp_path: Path, name: str) -> None:
    folder = tmp_path / "never"
    with pytest.raises(PublishError, match="not a plain file name"):
        publish_once(folder, name, DATA)
    assert not folder.exists()


def test_failed_publish_leaves_no_temp_file_and_no_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(publish.os, "link", _boom)
    with pytest.raises(OSError, match="disk full"):
        publish_once(tmp_path, "report.json", DATA)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(("racer", "wins"), [(b"{}\n", False), (DATA, True)])
def test_a_writer_that_wins_the_race_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, racer: bytes, wins: bool
) -> None:
    """Another writer publishes between our existence check and our link (forced via fsync)."""
    target = tmp_path / "report.json"
    real_fsync = publish.os.fsync

    def _racing_fsync(fd: int) -> None:
        real_fsync(fd)
        target.write_bytes(racer)

    monkeypatch.setattr(publish.os, "fsync", _racing_fsync)
    if wins:
        assert publish_once(tmp_path, "report.json", DATA) == target
    else:
        with pytest.raises(PublishError, match="refusing to overwrite"):
            publish_once(tmp_path, "report.json", DATA)
    assert target.read_bytes() == racer
    assert [p.name for p in tmp_path.iterdir()] == ["report.json"]


def test_temp_files_are_unique_per_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    real_link = publish.os.link

    def _spy(src: str, dst: Path) -> None:
        seen.append(Path(src).name)
        real_link(src, dst)

    monkeypatch.setattr(publish.os, "link", _spy)
    publish_once(tmp_path / "a", "report.json", DATA)
    publish_once(tmp_path / "b", "report.json", DATA)
    assert len(set(seen)) == 2
    assert all(n.startswith(".report.json.") for n in seen)
