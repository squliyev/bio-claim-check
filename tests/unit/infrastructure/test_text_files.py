"""Text reading: one error shape for files and package data."""

from pathlib import Path

import pytest

from bio_claim_check.infrastructure.text_files import ReadError, read_package_text, read_text_file

pytestmark = pytest.mark.unit


def test_reads_utf8(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("β-cell\n", encoding="utf-8")
    assert read_text_file(path) == "β-cell\n"


@pytest.mark.parametrize("data", [None, b"\xff\xfe"], ids=["missing", "undecodable"])
def test_unreadable_files_raise_a_read_error_naming_the_path(tmp_path: Path, data: bytes | None) -> None:
    path = tmp_path / "a.txt"
    if data is not None:
        path.write_bytes(data)
    with pytest.raises(ReadError, match=f"^{path}: cannot read: "):
        read_text_file(path)


def test_reads_package_data() -> None:
    assert "schema_version: 1" in read_package_text("data", "rulepacks", "default.yaml")


def test_missing_package_data_raises_a_read_error() -> None:
    with pytest.raises(ReadError, match=r"^package data data/nope\.yaml: cannot read: "):
        read_package_text("data", "nope.yaml")
