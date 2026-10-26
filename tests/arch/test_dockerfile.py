"""The image carries every committed file the app reads at run time, readable by its non-root user.

The app resolves these paths relative to the working directory, and a checkout can keep the publisher's
0600 modes, so a missing COPY or chmod only shows up when the container runs (H1 smoke).
"""

import re
from pathlib import Path

import pytest

from bio_claim_check.app.settings import CHECKPOINT_RESULT, SEALED_DATASET
from tests.support.paths import ROOT

pytestmark = pytest.mark.arch

RUNTIME_PATHS = (CHECKPOINT_RESULT, SEALED_DATASET)


def _covers(tree: str, path: Path) -> bool:
    return path.as_posix() == tree or path.as_posix().startswith(tree + "/")


def test_every_runtime_path_is_copied_then_made_readable_then_root_is_dropped() -> None:
    lines = (ROOT / "Dockerfile").read_text().splitlines()
    user = max(i for i, line in enumerate(lines) if line.startswith("USER "))
    copies = [
        (i, m.group(1)) for i, line in enumerate(lines) if (m := re.fullmatch(r"COPY (\S+) \./\1", line))
    ]
    chmods = [
        (i, m.group(1).split())
        for i, line in enumerate(lines)
        if (m := re.fullmatch(r"RUN chmod -R a\+rX\S* (.+)", line))
    ]
    for path in RUNTIME_PATHS:
        copied = [i for i, tree in copies if _covers(tree, path)]
        assert copied, f"{path} is not copied"
        readable = [i for i, targets in chmods if any(_covers(t, path) for t in targets)]
        assert any(copied[-1] < i < user for i in readable), f"{path}: need COPY, then chmod, then USER"
