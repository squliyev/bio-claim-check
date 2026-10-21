"""`corpus seal` / `corpus verify` and the container helpers they use: folder reading, the seal file."""

from pathlib import Path

import pytest
from tests.support.corpus import dataset_files
from typer.testing import CliRunner

from bio_claim_check.app import cli
from bio_claim_check.app.container import DatasetReadError, OutputConflictError, read_dataset, write_seal
from bio_claim_check.features.corpus.layout import DEV_SOURCES, MANIFEST, SEALED, SPEC
from bio_claim_check.features.corpus.seal import sealed_bytes

pytestmark = pytest.mark.unit
runner = CliRunner()


def _write(folder: Path, files: dict[str, bytes]) -> Path:
    for name, data in files.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return folder


def _invoke(*argv: str) -> tuple[int, str, str]:
    result = runner.invoke(cli.app, ["corpus", *argv])
    return result.exit_code, result.stdout, result.stderr


def test_read_dataset_keys_every_visible_file_by_posix_path(tmp_path: Path) -> None:
    files = dataset_files()
    _write(tmp_path, {**files, ".DS_Store": b"x", ".hidden/a": b"y"})
    assert read_dataset(tmp_path) == files


def test_read_dataset_refuses_a_missing_folder(tmp_path: Path) -> None:
    with pytest.raises(DatasetReadError, match="is not a folder"):
        read_dataset(tmp_path / "nope")


def test_write_seal_is_a_no_op_twice_and_refuses_a_different_seal(tmp_path: Path) -> None:
    path = write_seal(tmp_path, b"manifest")
    assert path.read_bytes() == sealed_bytes(b"manifest")
    assert write_seal(tmp_path, b"manifest") == path
    with pytest.raises(OutputConflictError):
        write_seal(tmp_path, b"other manifest")
    assert path.read_bytes() == sealed_bytes(b"manifest")


def test_seal_then_verify(tmp_path: Path) -> None:
    folder = _write(tmp_path, dataset_files())
    code, out, _ = _invoke("seal", "--dataset", str(folder))
    assert code == 0
    assert out == f"sealed: {folder / SEALED}\n"
    seal = (folder / SEALED).read_bytes()
    assert seal == sealed_bytes((folder / MANIFEST).read_bytes())
    code, out, _ = _invoke("verify", "--dataset", str(folder))
    assert code == 0
    assert out == f"{folder} is intact and sealed ({seal.decode().strip()}).\n"
    assert _invoke("seal", "--dataset", str(folder))[0] == 0  # same seal again: a no-op


def test_verify_without_a_seal_exits_7(tmp_path: Path) -> None:
    folder = _write(tmp_path, dataset_files())
    code, _, err = _invoke("verify", "--dataset", str(folder))
    assert code == cli.EXIT_DATASET
    assert err == f"{folder} is not intact (1 problem(s)):\n  - {SEALED} is missing\n"


def test_seal_refuses_a_broken_dataset_and_writes_nothing(tmp_path: Path) -> None:
    files = dataset_files()
    files[DEV_SOURCES] += b" "
    folder = _write(tmp_path, files)
    code, _, err = _invoke("seal", "--dataset", str(folder))
    assert code == cli.EXIT_DATASET
    assert f"{DEV_SOURCES} does not match its hash in {MANIFEST}" in err
    assert not (folder / SEALED).exists()


def test_seal_refuses_to_replace_a_wrong_seal(tmp_path: Path) -> None:
    folder = _write(tmp_path, {**dataset_files(), SEALED: sealed_bytes(b"something else")})
    code, _, err = _invoke("seal", "--dataset", str(folder))
    assert code == cli.EXIT_DATASET
    assert f"{SEALED} does not match {MANIFEST}" in err
    assert (folder / SEALED).read_bytes() == sealed_bytes(b"something else")


def test_a_tampered_sealed_dataset_fails_verify(tmp_path: Path) -> None:
    folder = _write(tmp_path, dataset_files())
    assert _invoke("seal", "--dataset", str(folder))[0] == 0
    (folder / "extra.txt").write_bytes(b"x")
    code, _, err = _invoke("verify", "--dataset", str(folder))
    assert code == cli.EXIT_DATASET
    assert "extra.txt is not part of the dataset" in err


def test_a_missing_folder_or_spec_exits_2(tmp_path: Path) -> None:
    code, _, err = _invoke("verify", "--dataset", str(tmp_path / "nope"))
    assert code == cli.EXIT_INPUT
    assert "is not a folder" in err
    files = dataset_files()
    del files[SPEC]
    folder = _write(tmp_path / "d", files)
    code, _, err = _invoke("seal", "--dataset", str(folder))
    assert code == cli.EXIT_INPUT
    assert err.startswith("Invalid corpus spec (1 problem(s)):\n")
