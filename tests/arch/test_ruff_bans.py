"""The ruff TID251 bans behave as documented: active in src/, relaxed only where intended."""

import subprocess

import pytest

from tests.support.paths import ROOT, VENV_BIN

pytestmark = pytest.mark.arch


def _tid251(filename: str, source: str) -> bool:
    done = subprocess.run(  # noqa: S603 — fixed absolute executable, no shell
        [
            str(VENV_BIN / "ruff"),
            "check",
            "--no-cache",
            "--select",
            "TID251",
            "--output-format",
            "concise",
            "--stdin-filename",
            filename,
            "-",
        ],
        input=source,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert done.returncode in {0, 1}, done.stderr
    return "TID251" in done.stdout


def test_src_cannot_import_tests() -> None:
    assert _tid251("src/bio_claim_check/common/x.py", "import tests.support\n")
    assert _tid251("src/bio_claim_check/common/x.py", "from tests.support import paths\n")


def test_tests_may_import_test_support() -> None:
    assert not _tid251("tests/unit/x.py", "import tests.support\n")


def test_env_access_banned_outside_settings() -> None:
    assert _tid251("src/bio_claim_check/engine/x.py", "import os\nos.environ.get('X')\n")
    assert _tid251("src/bio_claim_check/engine/x.py", "import os\nos.getenv('X')\n")
