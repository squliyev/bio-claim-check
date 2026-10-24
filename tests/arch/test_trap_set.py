"""Every committed trap set and trap result holds its invariants (I76, I77). A glob: zero files is fine.

Self-reported, like the challenge result: a result is checked against its set, the sealed dataset and the
freeze record it is named after (judge, verifier, writer-family flag) and recounted, which proves
consistency, not that a model produced it. The abstracts are not in the repository, so copying is the
author's call in the sheet; only what CI can recompute is claimed here.
"""

from pathlib import Path

import pytest

from bio_claim_check.app.container import default_rulepack, load_corpus_spec, read_dataset
from bio_claim_check.app.freeze import FREEZE_DIR, FreezeRecord
from bio_claim_check.app.models import model_catalog
from bio_claim_check.app.usecases.traps import result_problems, set_problems
from bio_claim_check.features.corpus.layout import SPEC
from tests.support.paths import ROOT

pytestmark = pytest.mark.arch

TRAPS = ROOT / "traps"
SETS = sorted(TRAPS.glob("*.jsonl"))
RESULTS = sorted((TRAPS / "results").glob("*.json"))


def _set_and_freeze(result: Path) -> tuple[Path, FreezeRecord]:
    """`results/<freeze>-<set stem>.json` names its set and the freeze record it ran under."""
    matches = [s for s in SETS if result.stem.endswith(f"-{s.stem}")]
    assert len(matches) == 1, f"{result.name} names no single committed set"
    freeze = ROOT / FREEZE_DIR / f"{result.stem.removesuffix(f'-{matches[0].stem}')}.json"
    assert freeze.is_file(), f"{result.name} names no committed freeze record"
    return matches[0], FreezeRecord.model_validate_json(freeze.read_bytes())


def test_every_committed_trap_set_holds_its_invariants() -> None:
    files, pack = read_dataset(ROOT / "datasets"), default_rulepack()
    spec = load_corpus_spec(ROOT / "datasets" / SPEC)
    problems = {p.name: set_problems(p.read_bytes(), files, spec, pack) for p in SETS}
    assert {name: found for name, found in problems.items() if found} == {}


def test_every_committed_trap_result_attests_its_set_dataset_and_freeze() -> None:
    files, catalog = read_dataset(ROOT / "datasets"), model_catalog()
    problems: dict[str, list[str]] = {}
    for path in RESULTS:
        trap_set, freeze = _set_and_freeze(path)
        problems[path.name] = result_problems(
            trap_set.read_bytes(),
            path.read_bytes(),
            files,
            judge_sha256=freeze.judge_sha256,
            verifier=str(freeze.judge.verifier["deployment"]),
            family_of=lambda deployment: catalog.lookup(deployment).family,
        )
    assert {name: found for name, found in problems.items() if found} == {}


def test_only_sets_and_results_are_committed_under_traps() -> None:
    allowed = {*SETS, *RESULTS, TRAPS / "README.md", TRAPS / "results"}
    stray = [p for p in TRAPS.rglob("*") if p not in allowed] if TRAPS.exists() else []
    assert stray == []  # no draft, sheet or abstract text: those stay under the var dir
