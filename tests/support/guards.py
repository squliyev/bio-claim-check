"""[TEST SUPPORT] Static guards for invariants that ruff and import-linter cannot express.

Each guard is a plain function ``check_x(path, text) -> list[Violation]`` so it can be proven on
synthetic input (positive and negative cases) and then run over the real repository. Guards inspect the
whole text; nothing is stripped, so a violation hidden in a comment or string is still seen.
"""

import ast
import importlib
import inspect
import io
import pkgutil
import re
import tokenize
from abc import ABC
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Protocol

PACKAGE_NAME = "bio_claim_check"
TEST_SUPPORT_TAG = "[TEST SUPPORT]"
_RING_TAG = re.compile(r"^\[RING:([a-z_/]+)\]")
_ADR_FIELDS = {
    "Status": re.compile(r"^- \*\*Status:\*\* (Proposed|Accepted|Deprecated|Superseded by \d{4})\s*$", re.M),
    "Date": re.compile(r"^- \*\*Date:\*\* \d{4}-\d{2}-\d{2}\s*$", re.M),
    "Enforced by": re.compile(r"^- \*\*Enforced by:\*\* \S.*$", re.M),
}


@dataclass(frozen=True, slots=True)
class Violation:
    guard: str
    path: Path
    line: int
    detail: str


def expected_ring(module: PurePosixPath) -> str:
    """Map a path relative to ``src/`` to its ring tag.

    ``bio_claim_check/__init__.py`` -> ``root``; ``app/settings.py`` -> ``app``;
    ``app/cli/__init__.py`` -> ``app/cli``; ``features/bench/stats.py`` -> ``features/bench``.
    """
    parts = module.parts
    if not parts or parts[0] != PACKAGE_NAME:
        raise ValueError(f"{module} is not inside {PACKAGE_NAME}/")
    inner = parts[1:]
    if len(inner) == 1:
        return "root"
    if len(inner) == 2:
        return inner[0]
    return f"{inner[0]}/{inner[1]}"


def _docstring(path: Path, text: str) -> str | None:
    return ast.get_docstring(ast.parse(text, filename=str(path)), clean=False)


def check_ring_header(path: Path, text: str, *, src_relative: PurePosixPath) -> list[Violation]:
    doc = _docstring(path, text)
    want = expected_ring(src_relative)
    if doc is None:
        return [Violation("ring-header", path, 1, f"missing module docstring; expected [RING:{want}]")]
    match = _RING_TAG.match(doc)
    if match is None:
        return [Violation("ring-header", path, 1, f"docstring must start with [RING:{want}]")]
    if match.group(1) != want:
        return [Violation("ring-header", path, 1, f"[RING:{match.group(1)}] but expected {want}")]
    return []


def check_test_support_header(path: Path, text: str) -> list[Violation]:
    doc = _docstring(path, text)
    if doc is None or not doc.startswith(TEST_SUPPORT_TAG):
        return [Violation("test-support-header", path, 1, f"docstring must start with {TEST_SUPPORT_TAG}")]
    return []


def check_adr_fields(path: Path, text: str) -> list[Violation]:
    return [
        Violation("adr-fields", path, 1, f"missing or malformed '- **{field}:**' line")
        for field, pattern in _ADR_FIELDS.items()
        if pattern.search(text) is None
    ]


class ImportGraph(Protocol):
    """The slice of ``grimp.ImportGraph`` the cycle guard needs (keeps the guard testable with a dict)."""

    @property
    def modules(self) -> Iterable[str]: ...
    def find_modules_directly_imported_by(self, module: str) -> Iterable[str]: ...


def check_no_ancestor_imports(graph: ImportGraph, root: str) -> list[Violation]:
    """Close the one cycle shape import-linter's ``acyclic_siblings`` cannot see.

    ``acyclic_siblings`` checks siblings at every depth, so any cycle that does not pass through a
    package's own ``__init__`` from below is caught there. The remaining shape is
    ``pkg/__init__ -> pkg.child -> pkg`` (a re-export loop). Forbidding a module from importing any of
    its ancestor packages removes it. The root package is exempt as an import target (modules may read
    ``__version__``) only because the root itself must import nothing internal, so it cannot sit on a
    cycle.
    """
    found: list[Violation] = []
    for module in sorted(graph.modules):
        if module != root and not module.startswith(f"{root}."):
            continue
        for imported in sorted(graph.find_modules_directly_imported_by(module)):
            internal = imported == root or imported.startswith(f"{root}.")
            if module == root and internal:
                found.append(
                    _cycle_violation(module, imported, "the root package must import nothing internal")
                )
            elif module.startswith(f"{imported}.") and imported != root:
                found.append(_cycle_violation(module, imported, "imports its own ancestor package"))
    return found


def _cycle_violation(module: str, imported: str, why: str) -> Violation:
    return Violation("no-ancestor-imports", Path(*module.split(".")), 0, f"{module} -> {imported}: {why}")


VERDICT_HOME = PurePosixPath(PACKAGE_NAME, "features", "contracts", "verdict.py")


def _dotted_tail(node: ast.expr) -> str:
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""


def check_verdict_construction(path: Path, text: str, *, src_relative: PurePosixPath) -> list[Violation]:
    """Outside contracts/verdict.py, a Verdict is made only by `Verdict.finalise` or `model_validate`.

    Flags `Verdict(...)`, `Verdict.model_construct(...)`, `BaseModel.model_copy(...)` (it skips the
    validated override), `getattr(..., "model_construct")`, and aliases (`import Verdict as V`,
    `V = Verdict`) that would hide the others. A backstop only: `Verdict.verify_against` is the
    integrity check.
    """
    if src_relative == VERDICT_HOME:
        return []
    found: list[Violation] = []

    def flag(node: ast.stmt | ast.expr, detail: str) -> None:
        found.append(Violation("verdict-construction", path, node.lineno, detail))

    for node in ast.walk(ast.parse(text, filename=str(path))):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == "Verdict" and a.asname not in (None, "Verdict"):
                    flag(node, f"Verdict imported as {a.asname}")
        elif isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            if _dotted_tail(node.value) == "Verdict":
                flag(node, "Verdict aliased by assignment")
        elif isinstance(node, ast.Call):
            name = _dotted_tail(node.func)
            owner = _dotted_tail(node.func.value) if isinstance(node.func, ast.Attribute) else ""
            if name == "Verdict" or (name == "model_construct" and owner == "Verdict"):
                flag(node, "use Verdict.finalise or model_validate")
            elif name == "model_copy" and owner == "BaseModel":
                flag(node, "BaseModel.model_copy skips validation")
            elif name == "getattr" and any(
                isinstance(arg, ast.Constant) and arg.value == "model_construct" for arg in node.args
            ):
                flag(node, "getattr(..., 'model_construct') hides a construction")
    return found


# ---------------------------------------------------------------- ports (ADR 0007)

BASE_PREFIX = "base_"
STUB_PREFIXES = frozenset(
    {"in_memory", "scripted"}
)  # driver-free implementations; everything else is a backend
LEGACY_STEMS = frozenset({"ports", "fakes"})  # replaced by base_<x>.py / in_memory_<x>.py / scripted_<x>.py
EXTENSION_POINT_TAG = "[EXTENSION POINT]"
LEAF_TAG = "[LEAF]"


def import_package(root: str) -> dict[str, ModuleType]:
    """Import ``root`` and every module below it. Guards read classes at runtime, not names in text."""
    package = importlib.import_module(root)
    found = {root: package}
    for info in pkgutil.walk_packages(package.__path__, f"{root}."):
        found[info.name] = importlib.import_module(info.name)
    return found


def _within(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


def _stem(module: str) -> str:
    return module.rsplit(".", 1)[-1]


def _parent(module: str) -> str:
    return module.rsplit(".", 1)[0]


def _pascal(snake: str) -> str:
    return "".join(word.capitalize() for word in snake.split("_"))


def _local_classes(module: ModuleType) -> list[type]:
    return [c for _, c in inspect.getmembers(module, inspect.isclass) if c.__module__ == module.__name__]


def _module_violation(guard: str, module: str, detail: str) -> Violation:
    return Violation(guard, Path(*module.split(".")), 0, f"{module}: {detail}")


@dataclass(frozen=True, slots=True)
class Port:
    base: type
    thing: str  # the <x> in base_<x>.py
    implementations: tuple[str, ...]  # modules holding a concrete subclass


def find_ports(modules: Mapping[str, ModuleType]) -> dict[str, Port]:
    """Well-formed bases (keyed by module) and the modules that implement them."""
    bases: dict[str, type] = {}
    for name, module in modules.items():
        stem = _stem(name)
        public = [c for c in _local_classes(module) if not c.__name__.startswith("_")]
        if stem.startswith(BASE_PREFIX) and len(public) == 1:
            bases[name] = public[0]
    return {
        name: Port(
            base,
            _stem(name).removeprefix(BASE_PREFIX),
            tuple(
                sorted(
                    impl
                    for impl, module in modules.items()
                    if any(issubclass(c, base) and not inspect.isabstract(c) for c in _local_classes(module))
                )
            ),
        )
        for name, base in sorted(bases.items())
    }


def backend_modules(modules: Mapping[str, ModuleType]) -> set[str]:
    """Implementation modules whose prefix is not a stub prefix: the only core modules allowed drivers."""
    return {
        impl
        for port in find_ports(modules).values()
        for impl in port.implementations
        if _stem(impl).removesuffix(f"_{port.thing}") not in STUB_PREFIXES
    }


def _imported_modules(module: ModuleType) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found |= {node.module} | {f"{node.module}.{a.name}" for a in node.names}
    return found


def check_port_shape(modules: Mapping[str, ModuleType], root: str) -> list[Violation]:
    """ADK-style ports (ADR 0007), checked on live classes so a name in a comment cannot satisfy it.

    - ``base_<x>.py`` defines exactly one public class, ``Base<X>``, an ABC with >=1 abstract method.
    - A concrete subclass of ``Base<X>`` lives in ``<prefix>_<x>.py`` beside its base; a base tagged
      ``[EXTENSION POINT]`` may be implemented in any ``features``/``engine`` package instead.
    - A base never imports its implementations; no ``Protocol`` in features/engine; no ports/fakes files.
    """
    guard = "port-shape"
    found: list[Violation] = []
    for name, module in sorted(modules.items()):
        stem = _stem(name)
        if stem in LEGACY_STEMS:
            found.append(
                _module_violation(
                    guard, name, f"{stem}.py is retired; use base_<x>.py and named implementations"
                )
            )
        if (_within(name, f"{root}.features") or _within(name, f"{root}.engine")) and (
            protocols := [c.__name__ for c in _local_classes(module) if getattr(c, "_is_protocol", False)]
        ):
            found.append(
                _module_violation(guard, name, f"Protocol ports are retired, use an ABC: {protocols}")
            )
        if not stem.startswith(BASE_PREFIX):
            continue
        want = f"Base{_pascal(stem.removeprefix(BASE_PREFIX))}"
        public = [c.__name__ for c in _local_classes(module) if not c.__name__.startswith("_")]
        if public != [want]:
            found.append(
                _module_violation(guard, name, f"must define exactly one public class {want}, found {public}")
            )
            continue
        base = getattr(module, want)
        if not (issubclass(base, ABC) and inspect.isabstract(base)):
            found.append(
                _module_violation(guard, name, f"{want} must be an ABC with at least one abstract method")
            )
    ports = find_ports(modules)
    for base_module, port in ports.items():
        extension = EXTENSION_POINT_TAG in (port.base.__doc__ or "")
        if leaked := sorted(_imported_modules(modules[base_module]) & set(port.implementations)):
            found.append(
                _module_violation(guard, base_module, f"a base never imports its implementations: {leaked}")
            )
        for impl in port.implementations:
            prefix = _stem(impl).removesuffix(f"_{port.thing}")
            if prefix in (_stem(impl), "", "base"):
                found.append(
                    _module_violation(
                        guard, impl, f"implements {port.base.__name__}: name it <backend>_{port.thing}.py"
                    )
                )
            elif extension and not (_within(impl, f"{root}.features") or _within(impl, f"{root}.engine")):
                found.append(
                    _module_violation(guard, impl, "extension points are implemented in features or engine")
                )
            elif not extension and _parent(impl) != _parent(base_module):
                found.append(_module_violation(guard, impl, f"implementations live beside {base_module}"))
    return found


def check_driver_imports(
    graph: ImportGraph, root: str, drivers: Iterable[str], backends: Iterable[str]
) -> list[Violation]:
    """Outside infrastructure and app, only backends import drivers, and nothing imports a backend.

    The second half keeps package imports cheap: a stub or a slice ``__init__`` that re-exports a backend
    would load its driver for everyone (ADR 0007).
    """
    driver_roots, backend_set = set(drivers), set(backends)
    outer = (f"{root}.infrastructure", f"{root}.app")
    found: list[Violation] = []
    for module in sorted(graph.modules):
        if not _within(module, root) or any(_within(module, o) for o in outer):
            continue
        for imported in sorted(graph.find_modules_directly_imported_by(module)):
            if imported.split(".")[0] in driver_roots and module not in backend_set:
                found.append(
                    _module_violation(
                        "driver-imports", module, f"imports driver {imported}; only backends may"
                    )
                )
            elif imported in backend_set:
                found.append(
                    _module_violation("driver-imports", module, f"imports backend {imported}; wire it in app")
                )
    return found


def implementation_classes(modules: Mapping[str, ModuleType], port: Port) -> set[type]:
    """The concrete subclasses of a port's base, read from the implementation modules."""
    return {
        c
        for impl in port.implementations
        for c in _local_classes(modules[impl])
        if issubclass(c, port.base) and not inspect.isabstract(c)
    }


def check_contract_suites(
    modules: Mapping[str, ModuleType], suites: Mapping[str, tuple[type, ...]]
) -> list[Violation]:
    """Every port with a backend has a shared contract suite run against all its implementations (I33).

    ``suites`` maps a port's ``<x>`` to the ``IMPLEMENTATIONS`` tuple of
    ``tests/contract/test_<x>_contract.py``
    (absent = no suite). Comparing classes, not imports, proves each implementation is actually run.
    """
    backends = backend_modules(modules)
    found: list[Violation] = []
    for base_module, port in find_ports(modules).items():
        if not set(port.implementations) & backends:
            continue  # stubs only: nothing real to hold to the contract yet
        if port.thing not in suites:
            found.append(
                _module_violation(
                    "contract-suites",
                    base_module,
                    f"has a backend but no tests/contract/test_{port.thing}_contract.py",
                )
            )
            continue
        want = implementation_classes(modules, port)
        got = set(suites[port.thing])
        if got != want:
            missing = sorted(c.__name__ for c in want - got)
            extra = sorted(c.__name__ for c in got - want)
            found.append(
                _module_violation(
                    "contract-suites",
                    base_module,
                    f"suite IMPLEMENTATIONS: missing {missing}, unexpected {extra}",
                )
            )
    return found


def marked_packages(modules: Mapping[str, ModuleType], tag: str) -> set[str]:
    return {name for name, m in modules.items() if hasattr(m, "__path__") and tag in (m.__doc__ or "")}


def check_internal_imports(
    graph: ImportGraph, root: str, source: str, allowed: Iterable[str], *, guard: str
) -> list[Violation]:
    """Every internal import made inside ``source`` stays in ``source`` or one of the ``allowed`` packages."""
    targets = (source, *allowed)
    found: list[Violation] = []
    for module in sorted(m for m in graph.modules if _within(m, source)):
        for imported in sorted(graph.find_modules_directly_imported_by(module)):
            if _within(imported, root) and not any(_within(imported, t) for t in targets):
                found.append(
                    _module_violation(guard, module, f"imports {imported}; allowed: {sorted(targets)}")
                )
    return found


def _dotted(node: ast.expr) -> str:
    match node:
        case ast.Call(func=func):
            return _dotted(func)
        case ast.Attribute(value=value, attr=attr):
            return f"{_dotted(value)}.{attr}"
        case ast.Name(id=name):
            return name
        case _:
            return ""


def check_no_registry(path: Path, text: str) -> list[Violation]:
    """Order and wiring live in the composition root, never in import side effects (ADR 0007).

    Rejects ``__init_subclass__``; module-level bare calls, item/attribute assignment and augmented
    assignment, also inside top-level ``if``/``try``/``with``/``for``/``while``; any module-scope call whose
    name contains ``regist`` (e.g. ``REG = build_registry()``); and ``register``-style decorators.
    Ordinary constant construction (``_RE = re.compile(...)``) stays legal.
    """
    tree = ast.parse(text, filename=str(path))
    found: list[Violation] = []

    def flag(node: ast.stmt, detail: str) -> None:
        found.append(Violation("no-registry", path, node.lineno, detail))

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "__init_subclass__":
            flag(node, "__init_subclass__ registers classes as a side effect")
    for stmt in _module_scope(tree.body):
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            flag(stmt, f"module-level call {_dotted(stmt.value)}() runs on import")
        elif isinstance(stmt, ast.AugAssign):
            flag(stmt, "module-level augmented assignment mutates shared state on import")
        elif isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Subscript | ast.Attribute) for t in stmt.targets
        ):
            flag(stmt, "module-level item/attribute assignment mutates shared state on import")
        elif isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            for deco in stmt.decorator_list:
                if "register" in _dotted(deco).lower():
                    flag(stmt, f"@{_dotted(deco)} registers on import")
        else:
            for node in ast.walk(stmt):
                if isinstance(node, ast.Call) and "regist" in _dotted(node).lower():
                    flag(stmt, f"module-level {_dotted(node)}() builds a registry on import")
                    break
    return found


def _module_scope(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Statements that run on import: the module body and the bodies of top-level control flow."""
    for stmt in body:
        match stmt:
            case ast.If(body=b, orelse=o) | ast.For(body=b, orelse=o) | ast.While(body=b, orelse=o):
                yield from _module_scope([*b, *o])
            case ast.With(body=b):
                yield from _module_scope(b)
            case (
                ast.Try(body=b, handlers=h, orelse=o, finalbody=f)
                | ast.TryStar(body=b, handlers=h, orelse=o, finalbody=f)
            ):
                yield from _module_scope([*b, *(s for x in h for s in x.body), *o, *f])
            case _:
                yield stmt


_SUPPRESSION = re.compile(
    r"#\s*(?:noqa(?::\s*[A-Z]+[0-9]+(?:\s*,\s*[A-Z]+[0-9]+)*)?"
    r"|pyright:\s*ignore(?:\[[^\]]*\])?)"
)
_REASON = re.compile(r"[^\W_]")


def check_suppression_reasons(path: Path, text: str) -> list[Violation]:
    """A ``# noqa`` or ``# pyright: ignore`` must say why (AGENTS.md, "Never weaken a check").

    The reason is text after the suppression on the same comment, or a comment-only line directly above.
    Comments are read with ``tokenize``, so a suppression spelled inside a string is not a suppression.
    """
    lines = text.splitlines()
    found: list[Violation] = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type != tokenize.COMMENT or not (m := _SUPPRESSION.search(tok.string)):
            continue
        if _REASON.search(tok.string[m.end() :]):
            continue
        row = tok.start[0]
        if row >= 2 and lines[row - 2].lstrip().startswith("#"):
            continue
        found.append(Violation("suppression-reason", path, row, f"{m.group(0)!r} without a reason"))
    return found
