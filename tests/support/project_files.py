"""[TEST SUPPORT] Parse the project documents that tests keep in sync with the code.

Each parser is strict: a malformed row raises instead of being skipped, so a typo can never make a
parity test pass vacuously.
"""

import ast
import re
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from tests.support.paths import VENV_BIN

_ROW = re.compile(r"^\| (I\d+) \|(.+)\|(.+)\|(.+)\|\s*$")
_REF = re.compile(r"^(import-linter|ruff|pytest|ci):(\S+)$")


@dataclass(frozen=True, slots=True)
class Invariant:
    id: str
    refs: tuple[str, ...]


REF_SEPARATOR = " · "


def parse_invariants(path: Path) -> list[Invariant]:
    rows: list[Invariant] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| I"):
            continue
        match = _ROW.match(line)
        if match is None:
            raise ValueError(f"malformed invariant row: {line!r}")
        cells = (match.group(3), match.group(4))
        refs = tuple(ref.strip() for cell in cells for ref in cell.split(REF_SEPARATOR))
        rows.append(Invariant(match.group(1), refs))
    if not rows:
        raise ValueError(f"no invariants found in {path}")
    return rows


def _defines(test_file: Path, name: str) -> bool:
    tree = ast.parse(test_file.read_text(encoding="utf-8"))
    return any(isinstance(n, ast.FunctionDef) and n.name == name for n in tree.body)


@dataclass(frozen=True, slots=True)
class RefContext:
    """What a reference may point at: test files under ``root``, contracts, ruff rules, CI jobs."""

    root: Path
    contract_ids: frozenset[str]
    ruff_select: frozenset[str]
    ci_jobs: frozenset[str]
    ruff_rule_exists: Callable[[str], bool]


def resolve(ref: str, ctx: RefContext) -> bool:
    """True if ``ref`` names something that exists.

    pytest refs are resolved statically (file exists and defines the function), so this works under any
    test selection and covers parametrized tests by their function name.
    """
    match = _REF.match(ref)
    if match is None:
        return False
    kind, target = match.groups()
    if kind == "import-linter":
        return target in ctx.contract_ids
    if kind == "ruff":
        return any(target.startswith(prefix) for prefix in ctx.ruff_select) and ctx.ruff_rule_exists(target)
    if kind == "ci":
        return target in ctx.ci_jobs
    file, sep, func = target.partition("::")
    path = ctx.root / file
    return bool(sep) and path.is_file() and _defines(path, func)


def ruff_select(pyproject: Path) -> frozenset[str]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return frozenset(cast(list[str], data["tool"]["ruff"]["lint"]["select"]))


def ci_jobs(workflow: Path) -> frozenset[str]:
    data = cast(dict[str, object], yaml.safe_load(workflow.read_text(encoding="utf-8")))
    return frozenset(cast(dict[str, object], data["jobs"]))


def ruff_rule_exists(code: str) -> bool:
    """Ask ruff itself, so a typo such as ``TID999`` cannot pass as a configured rule."""
    done = subprocess.run(  # noqa: S603 — fixed absolute executable, no shell
        [str(VENV_BIN / "ruff"), "rule", code], capture_output=True, text=True, check=False, timeout=60
    )
    return done.returncode == 0
