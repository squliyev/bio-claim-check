"""Canonical, content-addressed report files (S05)."""

import hashlib
import json
from pathlib import Path

import pytest

from bio_claim_check.app.container import build_fake_container
from bio_claim_check.app.usecases.run import run_question
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.infrastructure import run_store
from bio_claim_check.infrastructure.run_store import RunStoreError, canonical_bytes, run_id, write_report

pytestmark = pytest.mark.unit

REPORT = run_question(build_fake_container(), "Does OS-912 work?", AnswerMode.STRICT, k=4)


def test_canonical_bytes_are_sorted_utf8_with_a_trailing_newline() -> None:
    data = canonical_bytes(REPORT)
    assert data.endswith(b"}\n")
    assert (
        data == (json.dumps(json.loads(data), sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
    )


def test_run_id_is_a_16_hex_prefix_of_the_content_hash() -> None:
    assert run_id(REPORT) == hashlib.sha256(canonical_bytes(REPORT)).hexdigest()[:16]
    assert "run_id" not in canonical_bytes(REPORT).decode()


def test_write_is_idempotent(tmp_path: Path) -> None:
    first = write_report(tmp_path, REPORT)
    stamp = first.stat().st_mtime_ns
    assert write_report(tmp_path, REPORT) == first == tmp_path / run_id(REPORT) / "report.json"
    assert first.read_bytes() == canonical_bytes(REPORT)
    assert first.stat().st_mtime_ns == stamp
    assert [p.name for p in first.parent.iterdir()] == ["report.json"]


def test_refuses_to_overwrite_different_bytes(tmp_path: Path) -> None:
    target = tmp_path / run_id(REPORT) / "report.json"
    target.parent.mkdir()
    target.write_bytes(b"{}\n")
    with pytest.raises(RunStoreError, match="refusing to overwrite"):
        write_report(tmp_path, REPORT)
    assert target.read_bytes() == b"{}\n"


def test_failed_publish_leaves_no_temp_file_and_no_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(run_store.os, "link", _boom)
    with pytest.raises(OSError, match="disk full"):
        write_report(tmp_path, REPORT)
    assert list((tmp_path / run_id(REPORT)).iterdir()) == []


@pytest.mark.parametrize(("racer_bytes", "wins"), [(b"{}\n", False), (None, True)])
def test_a_writer_that_wins_the_race_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, racer_bytes: bytes | None, wins: bool
) -> None:
    """Another writer publishes between our existence check and our publish (forced via fsync)."""
    target = tmp_path / run_id(REPORT) / "report.json"
    racer = racer_bytes if racer_bytes is not None else canonical_bytes(REPORT)
    real_fsync = run_store.os.fsync

    def _racing_fsync(fd: int) -> None:
        real_fsync(fd)
        target.write_bytes(racer)

    monkeypatch.setattr(run_store.os, "fsync", _racing_fsync)
    if wins:
        assert write_report(tmp_path, REPORT) == target
    else:
        with pytest.raises(RunStoreError, match="refusing to overwrite"):
            write_report(tmp_path, REPORT)
    assert target.read_bytes() == racer
    assert [p.name for p in target.parent.iterdir()] == ["report.json"]


def test_temp_files_are_unique_per_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    real_link = run_store.os.link

    def _spy(src: str, dst: Path) -> None:
        seen.append(Path(src).name)
        real_link(src, dst)

    monkeypatch.setattr(run_store.os, "link", _spy)
    write_report(tmp_path / "a", REPORT)
    write_report(tmp_path / "b", REPORT)
    assert len(set(seen)) == 2
    assert all(n.startswith(".report.json.") for n in seen)
