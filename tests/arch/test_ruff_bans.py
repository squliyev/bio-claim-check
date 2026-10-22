"""The ruff TID251 bans behave as documented: active in src/, relaxed only where intended."""

import subprocess
import tomllib

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


@pytest.mark.parametrize(
    "source",
    [
        "from datetime import datetime\ndatetime.now()\n",
        "import datetime\ndatetime.datetime.utcnow()\n",
        "from datetime import date\ndate.today()\n",
        "import time\ntime.time()\n",
        "from time import perf_counter\nperf_counter()\n",
        "import random\n",
        "from random import choice\n",
        "import secrets\n",
        "import uuid\nuuid.uuid4()\n",
        "from datetime import datetime\ndatetime.today()\n",
        "import os\nos.urandom(8)\n",
        "import os\nos.getrandom(8)\n",
        "import time\ntime.monotonic_ns()\n",
        "import time\ntime.perf_counter_ns()\n",
    ],
)
def test_wall_clock_and_randomness_banned_in_src(source: str) -> None:
    assert _tid251("src/bio_claim_check/features/report/x.py", source)


def test_dynamic_imports_banned_in_src() -> None:
    assert _tid251(
        "src/bio_claim_check/features/report/x.py", "import importlib\nimportlib.import_module('httpx')\n"
    )


def test_deterministic_ids_stay_allowed() -> None:
    assert not _tid251(
        "src/bio_claim_check/features/report/x.py", "import uuid\nuuid.uuid5(uuid.NAMESPACE_URL, 'x')\n"
    )


@pytest.mark.parametrize("source", ["import json\njson.dumps({})\n", "from json import dump\n"])
def test_json_serialisation_banned_outside_canonical_json(source: str) -> None:
    assert _tid251("src/bio_claim_check/features/report/x.py", source)
    assert not _tid251("src/bio_claim_check/common/canonical_json.py", source)
    assert not _tid251("src/bio_claim_check/common/x.py", "import json\njson.loads('{}')\n")


def test_ban_exemptions_in_src_are_exactly_the_named_modules() -> None:
    """Each src exemption is one named module with an ADR (json.dumps: ADR 0013; wall clock: ADR 0016)."""
    lint = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]["lint"]
    exempt = {path for path, rules in lint["per-file-ignores"].items() if "TID251" in rules}
    assert {p for p in exempt if p.startswith("src/")} == {
        "src/bio_claim_check/common/canonical_json.py",
        "src/bio_claim_check/common/system_clock.py",
    }


def test_the_system_clock_is_the_one_wall_clock_exemption() -> None:
    source = "from datetime import UTC, datetime\ndatetime.now(UTC)\n"
    assert not _tid251("src/bio_claim_check/common/system_clock.py", source)
    assert _tid251("src/bio_claim_check/common/scripted_clock.py", source)
