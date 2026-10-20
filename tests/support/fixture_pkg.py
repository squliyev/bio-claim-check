"""[TEST SUPPORT] Prove the real import-linter contracts fire, using a throwaway package.

Why: a contract that never fails is decoration. This harness reads the contracts from the real
``pyproject.toml`` into typed objects, re-roots them onto a generated package ``fixturepkg``, plants
exactly one import, and runs the real ``lint-imports`` on ONE contract in isolation. That way one
violation cannot mask another, and a hand-copied approximation of the rules cannot drift.

Only the contract types this project uses are understood. Any other type or key raises, so the harness
can never silently ignore a rule it does not understand.
"""

import subprocess
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, cast, override

from tests.support.paths import VENV_BIN

FIXTURE_ROOT = "fixturepkg"


@dataclass(frozen=True, slots=True)
class LayersContract:
    id: str
    name: str
    layers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IndependenceContract:
    id: str
    name: str
    modules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ForbiddenContract:
    id: str
    name: str
    source_modules: tuple[str, ...]
    forbidden_modules: tuple[str, ...]
    allow_indirect_imports: bool = False


@dataclass(frozen=True, slots=True)
class AcyclicSiblingsContract:
    id: str
    name: str
    ancestors: tuple[str, ...]
    depth: int


type Contract = LayersContract | IndependenceContract | ForbiddenContract | AcyclicSiblingsContract

_KEYS: dict[str, set[str]] = {
    "layers": {"id", "name", "type", "layers"},
    "independence": {"id", "name", "type", "modules"},
    "forbidden": {"id", "name", "type", "source_modules", "forbidden_modules"},
    "acyclic_siblings": {"id", "name", "type", "ancestors", "depth"},
}
_OPTIONAL_KEYS: dict[str, set[str]] = {"forbidden": {"allow_indirect_imports"}}
_OPTIONS = {"root_package", "include_external_packages", "contracts"}
EXTERNAL = "ext:"  # case-module prefix for a third-party/stdlib module, e.g. "ext:httpx"


@dataclass(frozen=True, slots=True)
class LinterConfig:
    root: str
    include_external_packages: bool
    contracts: tuple[Contract, ...]


@dataclass(frozen=True, slots=True)
class ContractCase:
    """One regression case: plant ``importer -> imported`` and check ONE contract in isolation.

    Module names are relative to the root package. ``rogue`` must break the contract;
    ``allowed`` must keep it.
    """

    contract_id: str
    importer: str
    imported: str  # root-relative, or ``ext:<top-level module>`` for a third-party/stdlib module
    kind: Literal["rogue", "allowed"]
    also: tuple[tuple[str, str], ...] = ()  # extra planted imports, e.g. the return edge of a cycle

    @property
    def edges(self) -> tuple[tuple[str, str], ...]:
        return ((self.importer, self.imported), *self.also)

    @override
    def __str__(self) -> str:
        arrow = "-x->" if self.kind == "rogue" else "--->"
        extra = "".join(f"+{a}->{b}" for a, b in self.also)
        return f"{self.contract_id}:{self.importer}{arrow}{self.imported}{extra}"


class Outcome(StrEnum):
    KEPT = "kept"
    BROKEN = "broken"
    CONFIG_ERROR = "config-error"


@dataclass(frozen=True, slots=True)
class LintResult:
    returncode: int
    output: str  # stdout + stderr, whitespace collapsed (rich wraps long lines)

    def classify(self, contract_name: str) -> Outcome:
        """A config error (missing module, unknown contract) must never pass as a broken contract."""
        if (
            self.returncode == 0
            and f"{contract_name} KEPT" in self.output
            and "1 kept, 0 broken" in self.output
        ):
            return Outcome.KEPT
        if (
            self.returncode == 1
            and f"{contract_name} BROKEN" in self.output
            and "0 kept, 1 broken" in self.output
        ):
            return Outcome.BROKEN
        return Outcome.CONFIG_ERROR


def _str(raw: object, where: str) -> str:
    if not isinstance(raw, str):
        raise TypeError(f"{where}: expected a string, got {type(raw).__name__}")
    return raw


def _strs(raw: object, where: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise TypeError(f"{where}: expected a list, got {type(raw).__name__}")
    items = cast(list[object], raw)
    return tuple(_str(item, where) for item in items)


def load_contracts(pyproject: Path) -> LinterConfig:
    """Return the import-linter configuration exactly as written in ``pyproject.toml``."""
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))["tool"]["importlinter"]
    if unknown := set(config) - _OPTIONS:
        raise ValueError(f"unsupported import-linter options: {sorted(unknown)}")
    root = _str(config["root_package"], "root_package")
    externals = config.get("include_external_packages", False)
    if not isinstance(externals, bool):
        raise TypeError("include_external_packages: expected a bool")
    contracts: list[Contract] = []
    for raw in config["contracts"]:
        kind = _str(raw.get("type"), "type")
        optional = _OPTIONAL_KEYS.get(kind, set())
        if kind not in _KEYS or not _KEYS[kind] <= set(raw) <= _KEYS[kind] | optional:
            raise ValueError(f"unsupported contract shape: type={kind!r} keys={sorted(raw)}")
        cid, name = _str(raw["id"], "id"), _str(raw["name"], "name")
        if kind == "layers":
            contracts.append(LayersContract(cid, name, _strs(raw["layers"], cid)))
        elif kind == "independence":
            contracts.append(IndependenceContract(cid, name, _strs(raw["modules"], cid)))
        elif kind == "forbidden":
            indirect = raw.get("allow_indirect_imports", False)
            if not isinstance(indirect, bool):
                raise TypeError(f"{cid}: allow_indirect_imports must be a bool")
            contracts.append(
                ForbiddenContract(
                    cid,
                    name,
                    _strs(raw["source_modules"], cid),
                    _strs(raw["forbidden_modules"], cid),
                    indirect,
                )
            )
        else:
            depth = raw["depth"]
            if not isinstance(depth, int) or isinstance(depth, bool):
                raise TypeError(f"{cid}: depth must be an int")
            contracts.append(AcyclicSiblingsContract(cid, name, _strs(raw["ancestors"], cid), depth))
    return LinterConfig(root, externals, tuple(contracts))


def relative(module: str, root: str) -> str:
    """``root.a.b`` -> ``a.b``; the root itself -> ``""``. Anything else is rejected."""
    if module == root:
        return ""
    if not module.startswith(f"{root}."):
        raise ValueError(f"{module} is outside {root}")
    return module.removeprefix(f"{root}.")


def to_fixture(module: str, root: str) -> str:
    """Re-root one configured module name onto ``fixturepkg``.

    exact root -> ``fixturepkg``; descendant -> ``fixturepkg.<rest>``; a top-level external module
    (no dot, not the root) -> unchanged and never generated; anything else -> ValueError.
    """
    if module == root or module.startswith(f"{root}."):
        rest = relative(module, root)
        return f"{FIXTURE_ROOT}.{rest}" if rest else FIXTURE_ROOT
    if module.isidentifier():
        return module
    raise ValueError(f"cannot re-root {module!r}: neither inside {root} nor a top-level external module")


def case_target(module: str) -> str:
    """Case-module (root-relative or ``ext:x``) -> the name written in the planted import."""
    if module.startswith(EXTERNAL):
        return module.removeprefix(EXTERNAL)
    return f"{FIXTURE_ROOT}.{module}" if module else FIXTURE_ROOT


def _internal(modules: tuple[str, ...], root: str) -> tuple[str, ...]:
    return tuple(relative(m, root) for m in modules if m == root or m.startswith(f"{root}."))


def _modules(contract: Contract, root: str) -> tuple[str, ...]:
    """Root-relative internal modules a contract names (externals are never generated)."""
    match contract:
        case LayersContract(layers=layers):
            return _internal(layers, root)
        case IndependenceContract(modules=modules):
            return _internal(modules, root)
        case ForbiddenContract(source_modules=src, forbidden_modules=forbidden):
            return _internal(src + forbidden, root)
        case AcyclicSiblingsContract(ancestors=ancestors):
            return _internal(ancestors, root)


def _ini(contract: Contract, root: str) -> str:
    def rel(mods: tuple[str, ...]) -> str:
        return "".join(f"\n    {to_fixture(m, root)}" for m in mods)

    head = f"[importlinter:contract:{contract.id}]\nname = {contract.name}\n"
    match contract:
        case LayersContract(layers=layers):
            return f"{head}type = layers\nlayers ={rel(layers)}\n"
        case IndependenceContract(modules=modules):
            return f"{head}type = independence\nmodules ={rel(modules)}\n"
        case ForbiddenContract(source_modules=src, forbidden_modules=forbidden, allow_indirect_imports=ind):
            return (
                f"{head}type = forbidden\nsource_modules ={rel(src)}\nforbidden_modules ={rel(forbidden)}\n"
                f"allow_indirect_imports = {'true' if ind else 'false'}\n"
            )
        case AcyclicSiblingsContract(ancestors=ancestors, depth=depth):
            return f"{head}type = acyclic_siblings\nancestors ={rel(ancestors)}\ndepth = {depth}\n"


def _ensure_package(project: Path, module: str) -> Path:
    """Create ``fixturepkg/<module>`` and every parent as a package; return its ``__init__.py``."""
    path = project / FIXTURE_ROOT
    init = path / "__init__.py"
    path.mkdir(exist_ok=True)
    init.touch()
    for part in module.split(".") if module else []:
        path /= part
        path.mkdir(exist_ok=True)
        init = path / "__init__.py"
        init.touch()
    return init


def build_fixture_package(tmp: Path, config: LinterConfig, case: ContractCase) -> Path:
    """Generate a project whose only imports are ``case.edges``; return its directory."""
    project = tmp / "project"
    project.mkdir()
    for contract in config.contracts:
        for module in _modules(contract, config.root):
            _ensure_package(project, module)
    planted: dict[Path, list[str]] = {}
    for importer, imported in case.edges:
        if not imported.startswith(EXTERNAL):
            _ensure_package(project, imported)
        init = _ensure_package(project, importer)
        planted.setdefault(init, []).append(f"import {case_target(imported)}\n")
    for init, lines in planted.items():
        init.write_text("".join(lines), encoding="utf-8")
    body = "\n".join(_ini(c, config.root) for c in config.contracts)
    externals = "true" if config.include_external_packages else "false"
    (project / ".importlinter").write_text(
        f"[importlinter]\nroot_package = {FIXTURE_ROOT}\ninclude_external_packages = {externals}\n\n{body}",
        encoding="utf-8",
    )
    return project


def run_lint_imports(project: Path, contract_id: str) -> LintResult:
    """Run THIS venv's ``lint-imports`` on one contract, with a fixed environment and no cache.

    cwd is the generated project (import-linter puts the cwd on ``sys.path``); nothing is inherited
    from the developer's shell, so no stray PYTHONPATH can make a fixture pass.
    """
    exe = VENV_BIN / "lint-imports"
    if not exe.is_file():
        raise FileNotFoundError(f"{exe} missing: run `make sync`")
    done = subprocess.run(  # noqa: S603 — fixed absolute executable, no shell
        [str(exe), "--config", ".importlinter", "--contract", contract_id, "--no-cache", "--no-logo"],
        cwd=project,
        env={"PATH": str(VENV_BIN), "COLUMNS": "400", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return LintResult(done.returncode, " ".join((done.stdout + done.stderr).split()))
