"""Every committed trap set and trap result holds its invariants (I76, I77). A glob: zero files is fine.

Self-reported, like the challenge result: a result is checked against its set and recounted, which proves
consistency, not that a model produced it. The abstracts are not in the repository, so copying is the
author's call in the sheet; only what CI can recompute is claimed here.
"""

from pathlib import Path

import pytest

from bio_claim_check.app.container import default_rulepack, read_dataset
from bio_claim_check.app.usecases.traps import result_problems, set_problems
from tests.support.paths import ROOT

pytestmark = pytest.mark.arch

TRAPS = ROOT / "traps"
SETS = sorted(TRAPS.glob("*.jsonl"))
RESULTS = sorted((TRAPS / "results").glob("*.json"))


def _set_of(result: Path) -> Path:
    """`results/<freeze>-<set stem>.json` names its set."""
    matches = [s for s in SETS if result.stem.endswith(f"-{s.stem}")]
    assert len(matches) == 1, f"{result.name} names no single committed set"
    return matches[0]


def test_every_committed_trap_set_holds_its_invariants() -> None:
    files, pack = read_dataset(ROOT / "datasets"), default_rulepack()
    problems = {p.name: set_problems(p.read_bytes(), files, pack) for p in SETS}
    assert {name: found for name, found in problems.items() if found} == {}


def test_every_committed_trap_result_recounts_its_set() -> None:
    problems = {p.name: result_problems(_set_of(p).read_bytes(), p.read_bytes()) for p in RESULTS}
    assert {name: found for name, found in problems.items() if found} == {}


def test_only_sets_and_results_are_committed_under_traps() -> None:
    allowed = {*SETS, *RESULTS, TRAPS / "README.md", TRAPS / "results"}
    stray = [p for p in TRAPS.rglob("*") if p not in allowed] if TRAPS.exists() else []
    assert stray == []  # no draft, sheet or abstract text: those stay under the var dir
