"""[TEST SUPPORT] Static guards for invariants that ruff and import-linter cannot express.

Each guard is a plain function ``check_x(path, text) -> list[Violation]`` so it can be proven on
synthetic input (positive and negative cases) and then run over the real repository. Guards inspect the
whole text; nothing is stripped, so a violation hidden in a comment or string is still seen.
"""

import ast
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
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
