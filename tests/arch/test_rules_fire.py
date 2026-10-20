"""Every import-linter contract is proven live: it breaks on a planted import and keeps on a legal one.

Cases are run one contract at a time against a generated package built from the REAL contracts in
pyproject.toml (see tests/support/fixture_pkg.py). Parity tests make sure the contracts themselves still
describe the intended architecture, so a reorder or a forgotten slice fails here.
"""

from itertools import combinations, pairwise
from pathlib import Path

import pytest

from tests.support.fixture_pkg import (
    Contract,
    ContractCase,
    ForbiddenContract,
    IndependenceContract,
    LayersContract,
    Outcome,
    build_fixture_package,
    load_contracts,
    relative,
    run_lint_imports,
)
from tests.support.paths import FEATURES, PYPROJECT

pytestmark = pytest.mark.arch

ROOT, CONTRACTS = load_contracts(PYPROJECT)
EXPECTED_RINGS = ("app", "infrastructure", "features", "engine", "common")  # outermost first (ADR 0002)
SLICES = ("annotate", "answer", "baselines", "bench", "checks", "report", "retrieval", "traps", "verify")
DETERMINISTIC = ("features.annotate.agreement", "features.bench.stats", "features.checks")


def contract(cid: str) -> Contract:
    return next(c for c in CONTRACTS if c.id == cid)


def _ring_cases() -> list[ContractCase]:
    cases: list[ContractCase] = []
    for outer, inner in combinations(EXPECTED_RINGS, 2):
        cases.append(ContractCase("rings", inner, outer, "rogue"))  # every inner->outer pair breaks
    for outer, inner in pairwise(EXPECTED_RINGS):
        cases.append(ContractCase("rings", outer, inner, "allowed"))  # one legal control per boundary
    return cases


def _slice_cases() -> list[ContractCase]:
    cases = [
        ContractCase("slices", f"features.{a}", f"features.{b}", "rogue")
        for a, b in zip(SLICES, SLICES[1:] + SLICES[:1], strict=True)
    ]
    cases.append(ContractCase("slices", "features.verify", "features.contracts", "allowed"))
    return cases


CASES: list[ContractCase] = [
    *_ring_cases(),
    *_slice_cases(),
    *(ContractCase("no-llm-in-deterministic-code", s, "engine.llm", "rogue") for s in DETERMINISTIC),
    ContractCase("no-llm-in-deterministic-code", "features.bench", "engine.llm", "allowed"),  # runner may
    ContractCase("no-llm-in-deterministic-code", "features.verify", "engine.llm", "allowed"),
    ContractCase("contracts-do-not-depend-on-slices", "features.contracts", "features.verify", "rogue"),
    ContractCase("contracts-do-not-depend-on-slices", "features.contracts", "common", "allowed"),
]


@pytest.mark.parametrize("case", CASES, ids=str)
def test_contract_fires_only_on_rogue_imports(case: ContractCase, tmp_path: Path) -> None:
    project = build_fixture_package(tmp_path, ROOT, CONTRACTS, case)
    result = run_lint_imports(project, case.contract_id)
    outcome = result.classify(contract(case.contract_id).name)
    if case.kind == "rogue":
        assert outcome is Outcome.BROKEN, result.output
        assert f"fixturepkg.{case.importer} -> fixturepkg.{case.imported}" in result.output, result.output
    else:
        assert outcome is Outcome.KEPT, result.output


def test_every_contract_has_a_rogue_case() -> None:
    assert {c.id for c in CONTRACTS} == {c.contract_id for c in CASES if c.kind == "rogue"}


def test_rings_contract_matches_the_intended_order() -> None:
    rings = contract("rings")
    assert isinstance(rings, LayersContract)
    assert tuple(relative(m, ROOT) for m in rings.layers) == EXPECTED_RINGS


def test_slices_contract_lists_every_feature_package() -> None:
    on_disk = {p.name for p in FEATURES.iterdir() if (p / "__init__.py").is_file()} - {"contracts"}
    slices = contract("slices")
    assert isinstance(slices, IndependenceContract)
    assert {relative(m, ROOT).removeprefix("features.") for m in slices.modules} == on_disk == set(SLICES)


def test_deterministic_contract_sources_are_all_exercised() -> None:
    no_llm = contract("no-llm-in-deterministic-code")
    assert isinstance(no_llm, ForbiddenContract)
    assert {relative(m, ROOT) for m in no_llm.source_modules} == set(DETERMINISTIC)


def test_shared_contracts_forbid_every_slice() -> None:
    leaf = contract("contracts-do-not-depend-on-slices")
    assert isinstance(leaf, ForbiddenContract)
    assert {relative(m, ROOT).removeprefix("features.") for m in leaf.forbidden_modules} == set(SLICES)


def test_a_missing_module_is_a_config_error_not_a_pass(tmp_path: Path) -> None:
    """Guards the harness itself: a broken fixture must never be counted as a broken contract."""
    case = ContractCase("rings", "common", "features", "rogue")
    project = build_fixture_package(tmp_path, ROOT, CONTRACTS, case)
    (project / "fixturepkg" / "app" / "__init__.py").unlink()
    (project / "fixturepkg" / "app").rmdir()
    result = run_lint_imports(project, "rings")
    assert result.classify(contract("rings").name) is Outcome.CONFIG_ERROR, result.output


def test_an_unknown_contract_id_is_a_config_error(tmp_path: Path) -> None:
    case = ContractCase("rings", "app", "common", "allowed")
    project = build_fixture_package(tmp_path, ROOT, CONTRACTS, case)
    result = run_lint_imports(project, "no-such-contract")
    assert result.classify("no-such-contract") is Outcome.CONFIG_ERROR, result.output


def test_loader_rejects_unsupported_contract_shapes(tmp_path: Path) -> None:
    bad = tmp_path / "pyproject.toml"
    bad.write_text(
        '[tool.importlinter]\nroot_package = "x"\n'
        '[[tool.importlinter.contracts]]\nid = "a"\nname = "A"\ntype = "layers"\n'
        'layers = ["x.a"]\nignore_imports = ["x.a -> x.b"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported contract shape"):
        load_contracts(bad)
