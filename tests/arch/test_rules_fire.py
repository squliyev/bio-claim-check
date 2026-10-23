"""Every import-linter contract is proven live: it breaks on a planted import and keeps on a legal one.

Cases are run one contract at a time against a generated package built from the REAL contracts in
pyproject.toml (see tests/support/fixture_pkg.py). Parity tests make sure the contracts themselves still
describe the intended architecture, so a reorder or a forgotten slice fails here.
"""

import ast
import shutil
from itertools import combinations, pairwise
from pathlib import Path

import pytest

from tests.support.fixture_pkg import (
    EXTERNAL,
    FIXTURE_ROOT,
    AcyclicSiblingsContract,
    Contract,
    ContractCase,
    ForbiddenContract,
    IndependenceContract,
    LayersContract,
    Outcome,
    build_fixture_package,
    case_target,
    load_contracts,
    relative,
    run_lint_imports,
    to_fixture,
)
from tests.support.paths import FEATURES, PACKAGE, PYPROJECT

pytestmark = pytest.mark.arch

CONFIG = load_contracts(PYPROJECT)
ROOT, CONTRACTS = CONFIG.root, CONFIG.contracts
EXPECTED_RINGS = ("app", "infrastructure", "features", "engine", "common")  # outermost first (ADR 0002)
SLICES = (
    "annotate",
    "answer",
    "baselines",
    "bench",
    "checks",
    "corpus",
    "report",
    "retrieval",
    "traps",
    "verify",
)
PURE = (  # kinds that never import a driver; backends elsewhere are checked by the driver guard
    "app.run_record",
    "common",
    "engine.events",
    "features.annotate.agreement",
    "features.bench.stats",
    "features.checks",
    "features.contracts",
    "features.corpus",
    "features.report",
)
CORE_ALLOWED_EXTERNAL = "pydantic"  # the one third-party library pure modules may use today
NO_LLM_MARKER = "No LLM is involved"


def contract(cid: str) -> Contract:
    return next(c for c in CONTRACTS if c.id == cid)


def _forbidden(cid: str) -> ForbiddenContract:
    found = contract(cid)
    assert isinstance(found, ForbiddenContract)
    return found


DETERMINISTIC = tuple(relative(m, ROOT) for m in _forbidden("no-llm-in-deterministic-code").source_modules)


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


DRIVERS = "pure-modules-import-no-drivers"
ENGINE = "engine-is-feature-agnostic"
TRANSPORT = "infrastructure-holds-only-transport"
ADAPTERS = "driving-adapters-use-the-container"
USECASES = "usecases-are-interface-free"


def _driver_cases() -> list[ContractCase]:
    """One rogue case per forbidden library, rotating through the pure sources and a nested module."""
    io = _forbidden(DRIVERS)
    sources = (*PURE, "features.contracts.verdict")
    return [
        ContractCase(DRIVERS, sources[i % len(sources)], f"{EXTERNAL}{lib}", "rogue")
        for i, lib in enumerate(io.forbidden_modules)
    ]


CASES: list[ContractCase] = [
    *_ring_cases(),
    *_slice_cases(),
    *(ContractCase("no-llm-in-deterministic-code", s, "engine.llm", "rogue") for s in DETERMINISTIC),
    ContractCase("no-llm-in-deterministic-code", "features.bench", "engine.llm", "allowed"),  # runner may
    ContractCase("no-llm-in-deterministic-code", "features.verify", "engine.llm", "allowed"),
    ContractCase("contracts-do-not-depend-on-slices", "features.contracts", "features.verify", "rogue"),
    ContractCase("contracts-do-not-depend-on-slices", "features.contracts", "common", "allowed"),
    # cycles: one between rings (depth 1) and one inside a slice (depth 3) prove recursion
    ContractCase("no-cycles", "engine", "common", "rogue", also=(("common", "engine"),)),
    ContractCase(
        "no-cycles",
        "features.verify.a",
        "features.verify.b",
        "rogue",
        also=(("features.verify.b", "features.verify.a"),),
    ),
    ContractCase("no-cycles", "features.verify.a", "features.verify.b", "allowed"),  # one-way is fine
    *_driver_cases(),
    ContractCase(DRIVERS, "features.checks", f"{EXTERNAL}{CORE_ALLOWED_EXTERNAL}", "allowed"),
    ContractCase(DRIVERS, "features.verify.httpx_verifier", f"{EXTERNAL}httpx", "allowed"),  # a backend
    ContractCase(DRIVERS, "infrastructure", f"{EXTERNAL}httpx", "allowed"),
    ContractCase(DRIVERS, "app", f"{EXTERNAL}typer", "allowed"),  # the CLI lives in app
    # indirect: a pure module reaches a driver through another module; the whole chain is reported
    ContractCase(
        DRIVERS, "features.checks", "infrastructure", "rogue", also=(("infrastructure", f"{EXTERNAL}httpx"),)
    ),
    ContractCase(ENGINE, "engine.pipeline", "features.verify", "rogue"),
    ContractCase(ENGINE, "engine.events", "features.contracts", "rogue"),
    ContractCase(ENGINE, "engine.llm", "features.contracts", "rogue"),
    ContractCase(ENGINE, "engine", "infrastructure", "rogue"),
    ContractCase(ENGINE, "engine", "app", "rogue"),
    ContractCase(ENGINE, "features.verify", "engine.pipeline", "allowed"),  # features extend engine bases
    ContractCase(ENGINE, "features.contracts", "engine.events", "allowed"),  # domain events subclass
    ContractCase(TRANSPORT, "infrastructure", "features.report", "rogue"),
    ContractCase(TRANSPORT, "infrastructure", "engine.llm", "rogue"),
    ContractCase(TRANSPORT, "infrastructure", "common", "allowed"),
    ContractCase(TRANSPORT, "infrastructure", f"{EXTERNAL}yaml", "allowed"),
    ContractCase(ADAPTERS, "app.cli", "infrastructure", "rogue"),
    ContractCase(ADAPTERS, "app.ui", "infrastructure", "rogue"),
    ContractCase(  # the sanctioned path: through the container
        ADAPTERS, "app.cli", "app.container", "allowed", also=(("app.container", "infrastructure"),)
    ),
    ContractCase(USECASES, "app.usecases", "app.container", "rogue"),
    ContractCase(USECASES, "app.usecases", "app.cli", "rogue"),
    ContractCase(USECASES, "app.usecases", "app.ui", "rogue"),
    ContractCase(USECASES, "app.usecases", "infrastructure", "rogue"),
    ContractCase(USECASES, "app.usecases", "features.verify", "allowed"),
    ContractCase(USECASES, "app.container", "app.usecases", "allowed"),
]


def _cycle_evidence(case: ContractCase) -> tuple[str, set[str]]:
    """Cycle output names the parent package and nominates ONE planted edge (relative) as a breaker."""
    parent = case.importer.rsplit(".", 1)[0] if "." in case.importer else ""
    rel = {f"- .{a.rsplit('.', 1)[-1]} -> .{b.rsplit('.', 1)[-1]} (1 import)" for a, b in case.edges}
    return f"No cycles are allowed in {case_target(parent)}.", rel


@pytest.mark.parametrize("case", CASES, ids=str)
def test_contract_fires_only_on_rogue_imports(case: ContractCase, tmp_path: Path) -> None:
    project = build_fixture_package(tmp_path, CONFIG, case)
    result = run_lint_imports(project, case.contract_id)
    outcome = result.classify(contract(case.contract_id).name)
    if case.kind == "rogue":
        assert outcome is Outcome.BROKEN, result.output
        if isinstance(contract(case.contract_id), AcyclicSiblingsContract):
            header, breakers = _cycle_evidence(case)
            assert header in result.output, result.output
            assert any(b in result.output for b in breakers), result.output
        else:
            for importer, imported in case.edges:
                edge = f"{case_target(importer)} -> {case_target(imported)}"
                assert edge in result.output, result.output
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


def _module_name(path: Path) -> str:
    parts = path.relative_to(PACKAGE).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _marked_modules() -> set[str]:
    marked: set[str] = set()
    for path in PACKAGE.rglob("*.py"):
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
        if NO_LLM_MARKER in doc:
            marked.add(_module_name(path))
    return marked


def test_no_llm_sources_are_exactly_the_marked_modules() -> None:
    """The docstring marker is the source of truth: a marked module is covered (itself or an ancestor),
    and every contract source carries the marker. Marking a new module needs one contract line."""
    marked = _marked_modules()
    assert marked, "marker scan found nothing: did the marker wording change?"
    sources = set(DETERMINISTIC)
    uncovered = {m for m in marked if not any(m == s or m.startswith(f"{s}.") for s in sources)}
    assert not uncovered, f"marked 'No LLM' but not in no-llm-in-deterministic-code: {sorted(uncovered)}"
    assert sources <= marked, f"contract sources without the marker: {sorted(sources - marked)}"


def test_every_rogue_contract_case_has_an_allowed_control() -> None:
    rogue = {c.contract_id for c in CASES if c.kind == "rogue"}
    assert rogue == {c.contract_id for c in CASES if c.kind == "allowed"}


def test_shared_contracts_forbid_every_slice() -> None:
    leaf = contract("contracts-do-not-depend-on-slices")
    assert isinstance(leaf, ForbiddenContract)
    assert {relative(m, ROOT).removeprefix("features.") for m in leaf.forbidden_modules} == set(SLICES)


def test_pure_kinds_are_the_driver_free_sources() -> None:
    io = _forbidden(DRIVERS)
    assert tuple(relative(m, ROOT) for m in io.source_modules) == PURE
    assert set(PURE) <= set(DETERMINISTIC), "a driver-free pure module is also LLM-free"
    assert all("." not in m and not m.startswith(ROOT) for m in io.forbidden_modules)  # top-level externals
    assert CORE_ALLOWED_EXTERNAL not in io.forbidden_modules


def test_cycle_contract_covers_the_whole_package_at_full_depth() -> None:
    cycles = contract("no-cycles")
    assert isinstance(cycles, AcyclicSiblingsContract)
    assert cycles.ancestors == (ROOT,)
    deepest = max(len(p.relative_to(PACKAGE).parts) for p in PACKAGE.rglob("*.py"))
    assert deepest < cycles.depth, "package nesting reached the configured depth: raise `depth`"


def test_acyclic_siblings_misses_ancestor_reexport_cycles(tmp_path: Path) -> None:
    """Documents the known gap that tests/support/guards.check_no_ancestor_imports closes.

    If a future import-linter catches this, the test fails and the guard can be reconsidered.
    """
    case = ContractCase(
        "no-cycles",
        "features.verify",
        "features.verify.svc",
        "allowed",
        also=(("features.verify.svc", "features.verify"),),
    )
    project = build_fixture_package(tmp_path, CONFIG, case)
    result = run_lint_imports(project, "no-cycles")
    assert result.classify(contract("no-cycles").name) is Outcome.KEPT, result.output


def test_generated_config_mirrors_the_external_packages_option(tmp_path: Path) -> None:
    case = ContractCase("rings", "app", "common", "allowed")
    ini = (build_fixture_package(tmp_path, CONFIG, case) / ".importlinter").read_text(encoding="utf-8")
    assert CONFIG.include_external_packages is True
    assert "include_external_packages = true" in ini
    assert "\n    httpx" in ini
    assert f"{FIXTURE_ROOT}.httpx" not in ini


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("bio_claim_check", FIXTURE_ROOT),
        ("bio_claim_check.features.verify", f"{FIXTURE_ROOT}.features.verify"),
        ("httpx", "httpx"),
    ],
)
def test_to_fixture_reroots_internal_and_keeps_external(module: str, expected: str) -> None:
    assert to_fixture(module, ROOT) == expected


@pytest.mark.parametrize("module", ["other_pkg.sub", "bio_claim_checkx.a", "not a module"])
def test_to_fixture_rejects_anything_else(module: str) -> None:
    with pytest.raises(ValueError, match="cannot re-root"):
        to_fixture(module, ROOT)


def test_a_missing_module_is_a_config_error_not_a_pass(tmp_path: Path) -> None:
    """Guards the harness itself: a broken fixture must never be counted as a broken contract."""
    case = ContractCase("rings", "common", "features", "rogue")
    project = build_fixture_package(tmp_path, CONFIG, case)
    shutil.rmtree(project / "fixturepkg" / "app")
    result = run_lint_imports(project, "rings")
    assert result.classify(contract("rings").name) is Outcome.CONFIG_ERROR, result.output


def test_an_unknown_contract_id_is_a_config_error(tmp_path: Path) -> None:
    case = ContractCase("rings", "app", "common", "allowed")
    project = build_fixture_package(tmp_path, CONFIG, case)
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
