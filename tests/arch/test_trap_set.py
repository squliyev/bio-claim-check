"""Every committed trap set and trap result holds its invariants (I76, I77, I79). A glob: zero files is fine.

Self-reported, like the challenge result: a result is checked against its set, the sealed dataset and the
freeze record it is named after (judge, verifier, writer-family flag) and recounted, which proves
consistency, not that a model produced it. The abstracts are not in the repository, so copying is the
author's call in the sheet; only what CI can recompute is claimed here. A panel-confirmed set is
recomputed from its committed ledger of votes (I79); the votes themselves are self-reported too.
"""

from pathlib import Path

import pytest

from bio_claim_check.app.container import default_rulepack, load_corpus_spec, read_dataset
from bio_claim_check.app.freeze import FREEZE_DIR, FreezeRecord
from bio_claim_check.app.models import RATER_FAMILIES, model_catalog
from bio_claim_check.app.usecases.traps import panel_families, panel_problems, result_problems, set_problems
from bio_claim_check.common.model_family import ModelFamily
from bio_claim_check.features.corpus.layout import SPEC
from bio_claim_check.features.traps.panel import PanelLedger
from tests.support.paths import ROOT

pytestmark = pytest.mark.arch

TRAPS = ROOT / "traps"
SETS = sorted(TRAPS.glob("*.jsonl"))
RESULTS = sorted((TRAPS / "results").glob("*.json"))
LEDGERS = sorted(TRAPS.glob("*.panel.json"))
PROTOCOL = ROOT / "docs" / "protocols" / "trap-panel-v1.md"


def _ledger(trap_set: Path) -> bytes | None:
    path = trap_set.with_name(f"{trap_set.stem}.panel.json")
    return path.read_bytes() if path.is_file() else None


def _verifier_family(freeze_name: str) -> ModelFamily | None:
    path = ROOT / FREEZE_DIR / f"{freeze_name}.json"
    if not path.is_file():
        return None
    record = FreezeRecord.model_validate_json(path.read_bytes())
    return model_catalog().lookup(str(record.judge.verifier["deployment"])).family


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


def test_every_committed_trap_set_attests_who_confirmed_it() -> None:
    catalog, problems = model_catalog(), dict[str, list[str]]()
    for path in SETS:
        ledger = _ledger(path)
        freeze = PanelLedger.model_validate_json(ledger).intended_freeze if ledger is not None else None
        problems[path.name] = panel_problems(
            path.read_bytes(),
            ledger,
            protocol=PROTOCOL.read_bytes(),
            verifier_family=_verifier_family(freeze) if freeze is not None else None,
            rater_families=RATER_FAMILIES,
            writer_family_of=lambda deployment: catalog.lookup(deployment).family,
        )
    assert {name: found for name, found in problems.items() if found} == {}


def test_every_panel_ledger_belongs_to_a_committed_set() -> None:
    orphans = [p.name for p in LEDGERS if TRAPS / f"{p.name.removesuffix('.panel.json')}.jsonl" not in SETS]
    assert orphans == []


def test_every_committed_trap_result_attests_its_set_dataset_and_freeze() -> None:
    files, catalog = read_dataset(ROOT / "datasets"), model_catalog()
    problems: dict[str, list[str]] = {}
    for path in RESULTS:
        trap_set, freeze = _set_and_freeze(path)
        ledger = _ledger(trap_set)
        problems[path.name] = result_problems(
            trap_set.read_bytes(),
            path.read_bytes(),
            files,
            judge_sha256=freeze.judge_sha256,
            verifier=str(freeze.judge.verifier["deployment"]),
            family_of=lambda deployment: catalog.lookup(deployment).family,
            rater_families=panel_families(ledger, RATER_FAMILIES) if ledger is not None else frozenset(),
        )
    assert {name: found for name, found in problems.items() if found} == {}


def test_only_sets_and_results_are_committed_under_traps() -> None:
    allowed = {*SETS, *RESULTS, *LEDGERS, TRAPS / "README.md", TRAPS / "results"}
    stray = [p for p in TRAPS.rglob("*") if p not in allowed] if TRAPS.exists() else []
    assert stray == []  # no draft, sheet, rater reason or abstract text: those stay under the var dir
