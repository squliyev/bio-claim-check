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
from typing import Literal, cast

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


type Contract = LayersContract | IndependenceContract | ForbiddenContract

_KEYS: dict[str, set[str]] = {
    "layers": {"id", "name", "type", "layers"},
    "independence": {"id", "name", "type", "modules"},
    "forbidden": {"id", "name", "type", "source_modules", "forbidden_modules"},
}


@dataclass(frozen=True, slots=True)
class ContractCase:
    """One regression case: plant ``importer -> imported`` and check ONE contract in isolation.

    Module names are relative to the root package. ``rogue`` must break the contract;
    ``allowed`` must keep it.
    """

    contract_id: str
    importer: str
    imported: str
    kind: Literal["rogue", "allowed"]

    def __str__(self) -> str:
        arrow = "-x->" if self.kind == "rogue" else "--->"
        return f"{self.contract_id}:{self.importer}{arrow}{self.imported}"


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


def load_contracts(pyproject: Path) -> tuple[str, list[Contract]]:
    """Return ``(root_package, contracts)`` exactly as configured in ``pyproject.toml``."""
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))["tool"]["importlinter"]
    root = _str(config["root_package"], "root_package")
    if set(config) - {"root_package", "contracts"}:
        raise ValueError(f"unsupported import-linter options: {set(config) - {'root_package', 'contracts'}}")
    contracts: list[Contract] = []
    for raw in config["contracts"]:
        kind = _str(raw.get("type"), "type")
        if kind not in _KEYS or set(raw) != _KEYS[kind]:
            raise ValueError(f"unsupported contract shape: type={kind!r} keys={sorted(raw)}")
        cid, name = _str(raw["id"], "id"), _str(raw["name"], "name")
        if kind == "layers":
            contracts.append(LayersContract(cid, name, _strs(raw["layers"], cid)))
        elif kind == "independence":
            contracts.append(IndependenceContract(cid, name, _strs(raw["modules"], cid)))
        else:
            contracts.append(
                ForbiddenContract(
                    cid, name, _strs(raw["source_modules"], cid), _strs(raw["forbidden_modules"], cid)
                )
            )
    return root, contracts


def relative(module: str, root: str) -> str:
    if not module.startswith(f"{root}."):
        raise ValueError(f"{module} is outside {root}")
    return module.removeprefix(f"{root}.")


def _modules(contract: Contract) -> tuple[str, ...]:
    match contract:
        case LayersContract(layers=layers):
            return layers
        case IndependenceContract(modules=modules):
            return modules
        case ForbiddenContract(source_modules=src, forbidden_modules=forbidden):
            return src + forbidden


def _ini(contract: Contract, root: str) -> str:
    def rel(mods: tuple[str, ...]) -> str:
        return "".join(f"\n    {FIXTURE_ROOT}.{relative(m, root)}" for m in mods)

    head = f"[importlinter:contract:{contract.id}]\nname = {contract.name}\n"
    match contract:
        case LayersContract(layers=layers):
            return f"{head}type = layers\nlayers ={rel(layers)}\n"
        case IndependenceContract(modules=modules):
            return f"{head}type = independence\nmodules ={rel(modules)}\n"
        case ForbiddenContract(source_modules=src, forbidden_modules=forbidden):
            return (
                f"{head}type = forbidden\nsource_modules ={rel(src)}\nforbidden_modules ={rel(forbidden)}\n"
            )


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


def build_fixture_package(tmp: Path, root: str, contracts: list[Contract], case: ContractCase) -> Path:
    """Generate a project whose only import is ``case.importer -> case.imported``; return its directory."""
    project = tmp / "project"
    project.mkdir()
    for contract in contracts:
        for module in _modules(contract):
            _ensure_package(project, relative(module, root))
    _ensure_package(project, case.imported)
    importer = _ensure_package(project, case.importer)
    importer.write_text(f"import {FIXTURE_ROOT}.{case.imported}\n", encoding="utf-8")
    body = "\n".join(_ini(c, root) for c in contracts)
    (project / ".importlinter").write_text(
        f"[importlinter]\nroot_package = {FIXTURE_ROOT}\n\n{body}", encoding="utf-8"
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
