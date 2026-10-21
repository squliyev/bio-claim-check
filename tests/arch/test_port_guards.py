"""Generic guards from ADR 0007 (ports, drivers, leaves, registries): synthetic proof first, then the repo.

Every guard is described by *kind* (a file-name convention or a docstring tag), so a new slice, port or
backend passes without editing the rule. Synthetic packages are written under ``tmp_path`` and imported for
real, because the port guard reads live classes.
"""

import importlib
import inspect
import itertools
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import grimp
import pytest

from tests.arch import test_guards
from tests.support import guards
from tests.support.fixture_pkg import ForbiddenContract, load_contracts
from tests.support.guards import (
    BASE_PREFIX,
    EXTENSION_POINT_TAG,
    LEAF_TAG,
    PACKAGE_NAME,
    STUB_PREFIXES,
    backend_modules,
    check_contract_suites,
    check_driver_imports,
    check_internal_imports,
    check_no_registry,
    check_port_shape,
    find_ports,
    import_package,
    marked_packages,
)
from tests.support.paths import PYPROJECT, ROOT, SRC

CONTRACT_DIR = ROOT / "tests" / "contract"

pytestmark = pytest.mark.arch

_COUNTER = itertools.count()
BASE = (
    "from abc import ABC, abstractmethod\n\n\n"
    'class BaseThing(ABC):\n    """{doc}"""\n\n    @abstractmethod\n    def run(self) -> int: ...\n'
)
IMPL = (
    "from {pkg}.{base_pkg}.base_thing import BaseThing\n\n\n"
    "class {cls}(BaseThing):\n    def run(self) -> int:\n        return 1\n"
)
PROTOCOL = "from typing import Protocol\n\n\nclass Thing(Protocol):\n    def run(self) -> int: ...\n"
PLAIN = "class BaseThing:\n    def run(self) -> int:\n        return 1\n"

type Synth = Callable[[dict[str, str]], tuple[str, dict[str, ModuleType]]]


@pytest.fixture
def synth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Synth]:
    """Write ``{relative path: source}`` (``{pkg}`` is the package name) and import every module."""
    names: list[str] = []

    def build(files: dict[str, str]) -> tuple[str, dict[str, ModuleType]]:
        pkg = f"synthpkg{next(_COUNTER)}"
        names.append(pkg)
        for rel, source in {"__init__.py": "", **files}.items():
            path = tmp_path / pkg / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            for parent in path.relative_to(tmp_path).parents[:-1]:
                init = tmp_path / parent / "__init__.py"
                if not init.exists():
                    init.write_text("", encoding="utf-8")
            path.write_text(source.replace("{pkg}", pkg), encoding="utf-8")
        monkeypatch.setattr(sys, "path", [str(tmp_path), *sys.path])
        importlib.invalidate_caches()
        return pkg, import_package(pkg)

    yield build
    for module in [m for m in sys.modules if any(m == n or m.startswith(f"{n}.") for n in names)]:
        del sys.modules[module]


def _base(doc: str = "A port.") -> str:
    return BASE.replace("{doc}", doc)


def _impl(cls: str, base_pkg: str = "features.verify") -> str:
    return IMPL.replace("{base_pkg}", base_pkg).replace("{cls}", cls)


def _details(found: list[guards.Violation]) -> list[str]:
    return [v.detail for v in found]


# ---------------------------------------------------------------- port shape: synthetic


def test_port_shape_accepts_a_base_with_named_implementations(synth: Synth) -> None:
    pkg, modules = synth(
        {
            "features/verify/base_thing.py": _base(),
            "features/verify/in_memory_thing.py": _impl("InMemoryThing"),
            "features/verify/europe_pmc_thing.py": _impl("EuropePmcThing"),
        }
    )
    assert check_port_shape(modules, pkg) == []
    port = find_ports(modules)[f"{pkg}.features.verify.base_thing"]
    assert port.implementations == (
        f"{pkg}.features.verify.europe_pmc_thing",
        f"{pkg}.features.verify.in_memory_thing",
    )
    assert backend_modules(modules) == {f"{pkg}.features.verify.europe_pmc_thing"}


def test_port_shape_accepts_an_extension_point_implemented_in_another_slice(synth: Synth) -> None:
    pkg, modules = synth(
        {
            "engine/pipeline/base_thing.py": _base("[EXTENSION POINT] A processor base."),
            "features/checks/negation_thing.py": _impl("NegationThing", "engine.pipeline"),
        }
    )
    assert check_port_shape(modules, pkg) == []


@pytest.mark.parametrize(
    ("files", "fragment"),
    [
        pytest.param({"features/verify/ports.py": ""}, "ports.py is retired", id="legacy-ports"),
        pytest.param({"features/verify/fakes.py": ""}, "fakes.py is retired", id="legacy-fakes"),
        pytest.param(
            {"features/verify/x.py": PROTOCOL},
            "Protocol ports are retired",
            id="protocol",
        ),
        pytest.param(
            {"features/verify/base_thing.py": PLAIN},
            "must be an ABC",
            id="not-abc",
        ),
        pytest.param(
            {"features/verify/base_thing.py": "from abc import ABC\n\n\nclass BaseThing(ABC):\n    pass\n"},
            "must be an ABC with at least one abstract method",
            id="no-abstract-method",
        ),
        pytest.param(
            {"features/verify/base_thing.py": _base() + "\n\nclass Extra:\n    pass\n"},
            "exactly one public class BaseThing",
            id="extra-public-class",
        ),
        pytest.param(
            {"features/verify/base_thing.py": "from collections import OrderedDict as BaseThing\n"},
            "exactly one public class BaseThing",
            id="imported-not-defined",
        ),
        pytest.param(
            {"features/verify/base_thing.py": _base().replace("BaseThing", "BaseThings")},
            "exactly one public class BaseThing",
            id="wrong-name",
        ),
        pytest.param(
            {"features/verify/base_thing.py": _base(), "features/verify/memory.py": _impl("Memory")},
            "name it <backend>_thing.py",
            id="misnamed-implementation",
        ),
        pytest.param(
            {
                "features/verify/base_thing.py": _base()
                + "\n\nclass _Hidden(BaseThing):\n    def run(self) -> int:\n        return 2\n"
            },
            "name it <backend>_thing.py",
            id="implementation-inside-base",
        ),
        pytest.param(
            {
                "features/verify/base_thing.py": _base(),
                "features/answer/in_memory_thing.py": _impl("InMemoryThing"),
            },
            "implementations live beside",
            id="port-implemented-elsewhere",
        ),
        pytest.param(
            {
                "engine/pipeline/base_thing.py": _base("[EXTENSION POINT] base."),
                "infrastructure/x_thing.py": _impl("XThing", "engine.pipeline"),
            },
            "implemented in features or engine",
            id="extension-point-in-infrastructure",
        ),
        pytest.param(
            {
                "features/verify/base_thing.py": _base()
                + "\n\nfrom {pkg}.features.verify import in_memory_thing\n",
                "features/verify/in_memory_thing.py": _impl("InMemoryThing"),
            },
            "never imports its implementations",
            id="base-imports-implementation",
        ),
    ],
)
def test_port_shape_rejects(synth: Synth, files: dict[str, str], fragment: str) -> None:
    pkg, modules = synth(files)
    details = _details(check_port_shape(modules, pkg))
    assert any(fragment in d for d in details), details


# ---------------------------------------------------------------- drivers: synthetic


class _Graph:
    def __init__(self, edges: dict[str, set[str]]) -> None:
        self._edges = edges

    @property
    def modules(self) -> set[str]:
        return set(self._edges) | {m for targets in self._edges.values() for m in targets}

    def find_modules_directly_imported_by(self, module: str) -> set[str]:
        return self._edges.get(module, set())


BACKEND = "pkg.features.retrieval.europe_pmc_literature_source"


@pytest.mark.parametrize(
    "edges",
    [
        pytest.param({BACKEND: {"httpx", "tenacity"}}, id="backend"),
        pytest.param({"pkg.infrastructure.publish": {"sqlite3"}}, id="infrastructure"),
        pytest.param({"pkg.app.cli": {"typer", BACKEND}}, id="app-wires-backends"),
        pytest.param({"pkg.features.checks": {"pydantic", "pkg.common"}}, id="non-driver"),
        pytest.param({"other.x": {"httpx"}}, id="outside-root"),
    ],
)
def test_driver_guard_accepts(edges: dict[str, set[str]]) -> None:
    assert (
        check_driver_imports(_Graph(edges), "pkg", {"httpx", "sqlite3", "tenacity", "typer"}, {BACKEND}) == []
    )


@pytest.mark.parametrize(
    "edges",
    [
        pytest.param({"pkg.features.retrieval.base_literature_source": {"httpx"}}, id="base"),
        pytest.param(
            {"pkg.features.retrieval.in_memory_literature_source": {"httpx.client"}}, id="stub-submodule"
        ),
        pytest.param({"pkg.engine.cache": {"sqlite3"}}, id="engine-package"),
        pytest.param({"pkg.features.retrieval": {BACKEND}}, id="slice-reexports-backend"),
        pytest.param({"pkg.application": {"httpx"}}, id="name-prefix-is-not-app"),
        pytest.param(
            {BACKEND: {"pkg.features.retrieval.sqlite_literature_source"}}, id="backend-wires-backend"
        ),
    ],
)
def test_driver_guard_rejects(edges: dict[str, set[str]]) -> None:
    backends = {BACKEND, "pkg.features.retrieval.sqlite_literature_source"}
    assert len(check_driver_imports(_Graph(edges), "pkg", {"httpx", "sqlite3"}, backends)) == 1


# ---------------------------------------------------------------- contract suites: synthetic


_STUB_AND_BACKEND = {
    "features/verify/base_thing.py": _base(),
    "features/verify/in_memory_thing.py": _impl("InMemoryThing"),
    "features/verify/remote_thing.py": _impl("RemoteThing"),
}


def _classes(modules: dict[str, ModuleType], *names: str) -> tuple[type, ...]:
    return tuple(getattr(m, n) for m in modules.values() for n in names if hasattr(m, n))


def test_contract_suite_guard_accepts(synth: Synth) -> None:
    _, modules = synth(_STUB_AND_BACKEND)
    assert check_contract_suites(modules, {"thing": _classes(modules, "InMemoryThing", "RemoteThing")}) == []
    _, stubs_only = synth({k: v for k, v in _STUB_AND_BACKEND.items() if "remote" not in k})
    assert check_contract_suites(stubs_only, {}) == []


@pytest.mark.parametrize(
    ("suite", "fragment"),
    [
        pytest.param(None, "no tests/contract/test_thing_contract.py", id="no-suite"),
        pytest.param(("InMemoryThing",), "missing ['RemoteThing']", id="backend-not-run"),
        pytest.param(("RemoteThing",), "missing ['InMemoryThing']", id="stub-not-run"),
        pytest.param(("InMemoryThing", "RemoteThing", "int"), "unexpected ['int']", id="stray-class"),
    ],
)
def test_contract_suite_guard_rejects(synth: Synth, suite: tuple[str, ...] | None, fragment: str) -> None:
    _, modules = synth(_STUB_AND_BACKEND)
    suites: dict[str, tuple[type, ...]] = {}
    if suite is not None:
        suites["thing"] = tuple(int if n == "int" else _classes(modules, n)[0] for n in suite)
    (violation,) = check_contract_suites(modules, suites)
    assert fragment in violation.detail


# ---------------------------------------------------------------- internal imports: synthetic


@pytest.mark.parametrize(
    "edges",
    [
        pytest.param({"pkg.engine.events": {"pkg.common.ids", "pydantic"}}, id="common-and-external"),
        pytest.param({"pkg.engine.events.stage": {"pkg.engine.events"}}, id="within-itself"),
        pytest.param({"pkg.engine.eventsx": {"pkg.features"}}, id="name-prefix-is-not-inside"),
    ],
)
def test_internal_imports_guard_accepts(edges: dict[str, set[str]]) -> None:
    assert (
        check_internal_imports(_Graph(edges), "pkg", "pkg.engine.events", ["pkg.common"], guard="leaf") == []
    )


@pytest.mark.parametrize(
    "edges",
    [
        pytest.param({"pkg.engine.events": {"pkg.engine.llm"}}, id="sibling-engine"),
        pytest.param({"pkg.engine.events.stage": {"pkg.features.contracts"}}, id="nested-reaches-out"),
        pytest.param({"pkg.engine.events": {"pkg"}}, id="root-package"),
    ],
)
def test_internal_imports_guard_rejects(edges: dict[str, set[str]]) -> None:
    assert (
        len(check_internal_imports(_Graph(edges), "pkg", "pkg.engine.events", ["pkg.common"], guard="leaf"))
        == 1
    )


def test_marked_packages_reads_package_docstrings_only(synth: Synth) -> None:
    pkg, modules = synth(
        {"engine/events/__init__.py": f'"""{LEAF_TAG} x"""\n', "engine/llm.py": f'"""{LEAF_TAG} module"""\n'}
    )
    assert marked_packages(modules, LEAF_TAG) == {f"{pkg}.engine.events"}


# ---------------------------------------------------------------- no registry: synthetic


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("REGISTRY.append(X)\n", id="call"),
        pytest.param("register(X)\n", id="bare-call"),
        pytest.param("REGISTRY['x'] = X\n", id="item-assign"),
        pytest.param("other.HOOK = f\n", id="attribute-assign"),
        pytest.param("COUNT += 1\n", id="aug-assign"),
        pytest.param("class A:\n    def __init_subclass__(cls) -> None: ...\n", id="init-subclass"),
        pytest.param("@registry.register\nclass A: ...\n", id="decorator"),
        pytest.param("@register_processor('x')\ndef f() -> None: ...\n", id="decorator-call"),
        pytest.param("REGISTRY: dict[str, object] = build_registry()\n", id="registry-factory"),
        pytest.param("if enabled:\n    register(X)\n", id="call-inside-if"),
        pytest.param("try:\n    REG['x'] = X\nexcept KeyError:\n    pass\n", id="assign-inside-try"),
        pytest.param("for p in PLUGINS:\n    pass\nelse:\n    HOOKS += [p]\n", id="aug-inside-for-else"),
    ],
)
def test_no_registry_guard_rejects(text: str) -> None:
    assert len(check_no_registry(Path("x.py"), text)) == 1


@pytest.mark.parametrize(
    "text",
    [
        pytest.param('"""Docstring."""\nX: dict[str, int] = {}\nY = f(1)\n', id="assign-from-call"),
        pytest.param("@dataclass(frozen=True)\nclass A: ...\n", id="ordinary-decorator"),
        pytest.param("def f() -> None:\n    REG.append(1)\n    d['x'] = 1\n", id="inside-function"),
        pytest.param("if TYPE_CHECKING:\n    from x import Y\n", id="type-checking-block"),
    ],
)
def test_no_registry_guard_accepts(text: str) -> None:
    assert check_no_registry(Path("x.py"), text) == []


# ---------------------------------------------------------------- the real repository


@pytest.fixture(scope="module")
def real_modules() -> dict[str, ModuleType]:
    return import_package(PACKAGE_NAME)


@pytest.fixture(scope="module")
def real_graph() -> grimp.ImportGraph:
    return grimp.build_graph(PACKAGE_NAME, include_external_packages=True, cache_dir=None)


def _drivers() -> tuple[str, ...]:
    contract = next(
        c for c in load_contracts(PYPROJECT).contracts if c.id == "pure-modules-import-no-drivers"
    )
    assert isinstance(contract, ForbiddenContract)
    return contract.forbidden_modules


def test_the_real_ports_have_the_adk_shape(real_modules: dict[str, ModuleType]) -> None:
    """Kind-based, so a new port or backend passes without editing this test (ADR 0007 §9)."""
    assert check_port_shape(real_modules, PACKAGE_NAME) == []
    ports = find_ports(real_modules)
    base_files = {n for n in real_modules if n.rsplit(".", 1)[-1].startswith(BASE_PREFIX)}
    assert base_files, "discovery found no base modules"
    assert set(ports) == base_files, "every base_*.py is a discovered port"
    for base, port in ports.items():
        if EXTENSION_POINT_TAG in (port.base.__doc__ or ""):
            continue  # processors have no stub requirement
        stems = [i.rsplit(".", 1)[-1] for i in port.implementations]
        assert any(st.startswith(tuple(f"{p}_" for p in STUB_PREFIXES)) for st in stems), (
            f"{base} needs a driver-free in_memory_/scripted_ implementation"
        )


def test_only_backends_import_drivers(
    real_modules: dict[str, ModuleType], real_graph: grimp.ImportGraph
) -> None:
    assert "typer" in real_graph.modules, "externals not in the graph: the guard would see nothing"
    assert check_driver_imports(real_graph, PACKAGE_NAME, _drivers(), backend_modules(real_modules)) == []


def test_every_port_with_a_backend_has_a_contract_suite(real_modules: dict[str, ModuleType]) -> None:
    """I33. Kind-based: a new backend fails here until its port's suite runs it."""
    suites: dict[str, tuple[type, ...]] = {}
    for path in sorted(CONTRACT_DIR.glob("test_*_contract.py")):
        module = importlib.import_module(f"tests.contract.{path.stem}")
        suites[path.stem.removeprefix("test_").removesuffix("_contract")] = module.IMPLEMENTATIONS
    assert {"cache", "literature_source"} <= set(suites), "contract suites not found"
    assert check_contract_suites(real_modules, suites) == []


def test_leaf_packages_import_only_common(
    real_modules: dict[str, ModuleType], real_graph: grimp.ImportGraph
) -> None:
    leaves = marked_packages(real_modules, LEAF_TAG)
    assert f"{PACKAGE_NAME}.engine.events" in leaves
    common = f"{PACKAGE_NAME}.common"
    assert [
        v
        for leaf in sorted(leaves)
        for v in check_internal_imports(real_graph, PACKAGE_NAME, leaf, [common], guard="leaf")
    ] == []


def test_contracts_import_only_common_and_leaves(
    real_modules: dict[str, ModuleType], real_graph: grimp.ImportGraph
) -> None:
    allowed = [f"{PACKAGE_NAME}.common", *sorted(marked_packages(real_modules, LEAF_TAG))]
    contracts = f"{PACKAGE_NAME}.features.contracts"
    assert any(m.startswith(f"{contracts}.") for m in real_graph.modules)
    assert (
        check_internal_imports(real_graph, PACKAGE_NAME, contracts, allowed, guard="contracts-purity") == []
    )


def test_core_has_no_import_time_registries() -> None:
    core = [
        f
        for ring in ("common", "engine", "features")
        for f in sorted((SRC / PACKAGE_NAME / ring).rglob("*.py"))
    ]
    assert core
    assert [v for f in core for v in check_no_registry(f, f.read_text(encoding="utf-8"))] == []


def test_importing_every_core_package_loads_no_driver(real_modules: dict[str, ModuleType]) -> None:
    """ADK's lazy backends without ``__getattr__``: slice packages never re-export a backend."""
    packages = sorted(
        name
        for name, m in real_modules.items()
        if hasattr(m, "__path__")
        and any(name.startswith(f"{PACKAGE_NAME}.{r}") for r in ("common", "engine", "features"))
    )
    assert packages
    script = (
        f"import sys\nfor p in {packages!r}:\n    __import__(p)\n"
        f"print(sorted({{m.split('.')[0] for m in sys.modules}} & {set(_drivers())!r}))\n"
    )
    done = subprocess.run(  # noqa: S603 — this interpreter, fixed script, no shell
        [sys.executable, "-c", script], capture_output=True, text=True, check=True, timeout=60
    )
    assert done.stdout.strip() == "[]", done.stdout


# ---------------------------------------------------------------- guard parity


GUARD_TESTS = {  # every public guard has an accepting and a rejecting synthetic test
    "check_adr_fields": ("test_adr_fields_accepts_a_complete_header", "test_adr_fields_rejects"),
    "check_contract_suites": ("test_contract_suite_guard_accepts", "test_contract_suite_guard_rejects"),
    "check_driver_imports": ("test_driver_guard_accepts", "test_driver_guard_rejects"),
    "check_internal_imports": ("test_internal_imports_guard_accepts", "test_internal_imports_guard_rejects"),
    "check_no_ancestor_imports": ("test_ancestor_guard_accepts", "test_ancestor_guard_rejects"),
    "check_no_registry": ("test_no_registry_guard_accepts", "test_no_registry_guard_rejects"),
    "check_port_shape": (
        "test_port_shape_accepts_a_base_with_named_implementations",
        "test_port_shape_rejects",
    ),
    "check_ring_header": ("test_ring_header_accepts_matching_tag", "test_ring_header_rejects"),
    "check_test_support_header": (
        "test_test_support_header_accepts_and_rejects",
        "test_test_support_header_accepts_and_rejects",
    ),
    "check_suppression_reasons": (
        "test_suppression_reason_guard_accepts",
        "test_suppression_reason_guard_rejects",
    ),
    "check_verdict_construction": ("test_verdict_guard_accepts", "test_verdict_guard_rejects"),
}


def test_every_guard_has_an_accepting_and_a_rejecting_test() -> None:
    public = {n for n, _ in inspect.getmembers(guards, inspect.isfunction) if n.startswith("check_")}
    assert public == set(GUARD_TESTS)
    here = {**vars(test_guards), **globals()}
    missing = [t for pair in GUARD_TESTS.values() for t in pair if not callable(here.get(t))]
    assert not missing, missing
