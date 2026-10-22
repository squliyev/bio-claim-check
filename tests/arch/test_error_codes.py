"""Every deliberate error is a `BccError` with a unique code, and docs/error-codes.md lists exactly those
codes and the CLI's exit codes (I49). Rule-fire proofs show each check fails on a planted case."""

import ast
import re

import pytest

from bio_claim_check.app.cli import ExitCode
from bio_claim_check.common.errors import CODE_PATTERN, BccError
from tests.support.guards import import_package
from tests.support.paths import ROOT

pytestmark = pytest.mark.arch

DOC = ROOT / "docs" / "error-codes.md"
CLI = ROOT / "src" / "bio_claim_check" / "app" / "cli" / "__init__.py"
_ERROR_ROW = re.compile(r"^\| `([a-z_.]+)` \| `(\w+)` \| [^|]+\|$")
_EXIT_ROW = re.compile(r"^\| (\d+) \| `([A-Z_]+)` \| [^|]+\|$")


def _doc_rows(pattern: re.Pattern[str]) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if match := pattern.match(line):
            assert match.group(1) not in rows, f"duplicate row {match.group(1)}"
            rows[match.group(1)] = match.group(2)
    assert rows, f"no rows parsed from {DOC}; the table format changed"
    return rows


def _all_subclasses(base: type) -> set[type]:
    found: set[type] = set()
    for sub in base.__subclasses__():
        found |= {sub, *_all_subclasses(sub)}
    return found


def _package_errors() -> set[type[BccError]]:
    import_package("bio_claim_check")
    return {c for c in _all_subclasses(BccError) if c.__module__.startswith("bio_claim_check.")}


def _named_errors_outside_the_base() -> list[str]:
    modules = import_package("bio_claim_check")
    return sorted(
        f"{name}.{attr}"
        for name, module in modules.items()
        for attr, value in vars(module).items()
        if isinstance(value, type)
        and value.__module__ == name
        and issubclass(value, BaseException)
        and not issubclass(value, BccError)
    )


def code_problems(classes: set[type[BccError]]) -> list[str]:
    """Classes that do not declare their own code matching `CODE_PATTERN` (inheriting one does not count)."""
    problems: list[str] = []
    for cls in sorted(classes, key=lambda c: c.__qualname__):
        code = cls.__dict__.get("code")
        if not isinstance(code, str) or not CODE_PATTERN.fullmatch(code):
            problems.append(f"{cls.__qualname__}: {code!r}")
    return problems


def duplicate_codes(classes: set[type[BccError]]) -> list[str]:
    seen: dict[str, str] = {}
    clashes: list[str] = []
    for cls in sorted(classes, key=lambda c: c.__qualname__):
        if cls.code in seen:
            clashes.append(f"{cls.code}: {seen[cls.code]} and {cls.__qualname__}")
        seen.setdefault(cls.code, cls.__qualname__)
    return clashes


def int_literal_exits(source: str) -> list[int]:
    """Line numbers of `typer.Exit(code=<int literal>)` / `typer.Exit(<int literal>)`."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("Exit"):
            args = [*node.args, *(k.value for k in node.keywords if k.arg == "code")]
            if any(isinstance(a, ast.Constant) and isinstance(a.value, int) for a in args):
                lines.append(node.lineno)
    return lines


def test_every_exception_class_in_the_package_is_a_bcc_error() -> None:
    assert _named_errors_outside_the_base() == []


def test_codes_are_unique_and_match_the_doc() -> None:
    classes = _package_errors()
    assert len(classes) >= 19
    assert code_problems(classes) == []
    assert duplicate_codes(classes) == []
    assert {c.code: c.__name__ for c in classes} == _doc_rows(_ERROR_ROW)


def test_exit_codes_match_the_doc() -> None:
    assert {str(e.value): e.name for e in ExitCode} == _doc_rows(_EXIT_ROW)


def test_readme_links_the_table() -> None:
    assert "docs/error-codes.md" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_cli_never_exits_with_a_bare_integer() -> None:
    assert int_literal_exits(CLI.read_text(encoding="utf-8")) == []


# ---------------------------------------------------------------- rule-fire proofs


def test_proof_missing_bad_and_inherited_codes_are_found() -> None:
    missing = type("Missing", (BccError,), {})
    bad = type("Bad", (BccError,), {"code": "NoDots"})
    parent = type("Parent", (BccError,), {"code": "proof.parent"})
    child = type("Child", (parent,), {})
    assert code_problems({missing, bad, parent, child}) == ["Bad: 'NoDots'", "Child: None", "Missing: None"]


def test_proof_duplicate_codes_are_found() -> None:
    a = type("A", (BccError,), {"code": "proof.same"})
    b = type("B", (BccError,), {"code": "proof.same"})
    assert duplicate_codes({a, b}) == ["proof.same: A and B"]


def test_proof_bare_integer_exits_are_found() -> None:
    planted = "import typer\nraise typer.Exit(code=2)\nraise typer.Exit(3)\nraise typer.Exit(code=X.INPUT)\n"
    assert int_literal_exits(planted) == [2, 3]


def test_proof_code_pattern() -> None:
    assert CODE_PATTERN.fullmatch("cache.miss")
    assert not CODE_PATTERN.fullmatch("cache")
    assert not CODE_PATTERN.fullmatch("Cache.miss")


def test_doc_parser_is_strict() -> None:
    assert not _ERROR_ROW.match("| cache.miss | CacheMissError | x |")  # backticks are required
