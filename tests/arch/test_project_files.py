"""Project documents stay in sync with the code: ADR index, invariants, citation, issue forms, wheel."""

import re
import subprocess
import zipfile
from pathlib import Path
from typing import cast

import pytest
import yaml

from tests.support.fixture_pkg import load_contracts
from tests.support.paths import ADR_DIR, DOCS, PYPROJECT, ROOT, VENV_BIN
from tests.support.project_files import (
    RefContext,
    ci_jobs,
    parse_invariants,
    resolve,
    ruff_rule_exists,
    ruff_select,
)

pytestmark = pytest.mark.arch


def test_adr_index_lists_exactly_the_adr_files() -> None:
    files = {p.name for p in ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")}
    linked = set(
        re.findall(r"\]\(\./(\d{4}-[^)]+\.md)\)", (ADR_DIR / "README.md").read_text(encoding="utf-8"))
    )
    assert files
    assert files == linked


def test_adr_numbers_are_unique_and_titles_match_filenames() -> None:
    numbers = [p.name[:4] for p in ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")]
    assert len(numbers) == len(set(numbers))
    for path in ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"):
        assert path.read_text(encoding="utf-8").startswith(f"# ADR {path.name[:4]} — ")


def _context() -> RefContext:
    contracts = load_contracts(PYPROJECT).contracts
    return RefContext(
        root=ROOT,
        contract_ids=frozenset(c.id for c in contracts),
        ruff_select=ruff_select(PYPROJECT),
        ci_jobs=ci_jobs(ROOT / ".github" / "workflows" / "ci.yml"),
        ruff_rule_exists=ruff_rule_exists,
    )


def test_every_invariant_reference_resolves() -> None:
    ctx = _context()
    invariants = parse_invariants(DOCS / "invariants.md")
    unresolved = [(inv.id, ref) for inv in invariants for ref in inv.refs if not resolve(ref, ctx)]
    assert unresolved == []


def test_every_import_linter_contract_is_an_invariant() -> None:
    text = (DOCS / "invariants.md").read_text(encoding="utf-8")
    assert _context().contract_ids <= set(re.findall(r"import-linter:(\S+)", text))


@pytest.mark.parametrize(
    "bad",
    [
        "pytest:t.py::test_b",
        "pytest:missing.py::test_a",
        "pytest:t.py",
        "import-linter:nope",
        "ruff:XYZ1",
        "ruff:TID999",  # configured prefix, nonexistent rule
        "ci:deploy",
        "(same)",
        "free text",
    ],
)
def test_invariant_resolver_rejects_dangling_references(bad: str, tmp_path: Path) -> None:
    (tmp_path / "t.py").write_text("def test_a() -> None: ...\n", encoding="utf-8")
    ctx = RefContext(
        tmp_path, frozenset({"rings"}), frozenset({"TID"}), frozenset({"secrets"}), ruff_rule_exists
    )
    assert resolve("pytest:t.py::test_a", ctx)
    assert resolve("ruff:TID251", ctx)
    assert not resolve(bad, ctx)


def test_invariant_parser_rejects_malformed_rows(tmp_path: Path) -> None:
    doc = tmp_path / "inv.md"
    doc.write_text("| I1 | only two | columns |\n", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        parse_invariants(doc)


def test_invariant_parser_splits_multiple_refs(tmp_path: Path) -> None:
    doc = tmp_path / "inv.md"
    doc.write_text("| I1 | text | ruff:A · ci:b | pytest:c |\n", encoding="utf-8")
    assert parse_invariants(doc)[0].refs == ("ruff:A", "ci:b", "pytest:c")


def test_citation_cff_metadata_smoke() -> None:
    """A smoke test, not full CFF schema validation: required keys and author shape."""
    cff = cast(dict[str, object], yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8")))
    assert cff["cff-version"] == "1.2.0"
    assert cff["license"] == "Apache-2.0"
    assert {"message", "title", "type", "authors", "version", "repository-code"} <= cff.keys()
    authors = cast(list[dict[str, object]], cff["authors"])
    assert authors
    assert all({"family-names", "given-names"} <= a.keys() for a in authors)
    pyproject_version = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.M)
    assert pyproject_version is not None
    assert cff["version"] == pyproject_version.group(1)


@pytest.mark.parametrize(
    "form", sorted((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml")), ids=lambda p: p.name
)
def test_issue_forms_are_well_formed(form: Path) -> None:
    data = cast(dict[str, object], yaml.safe_load(form.read_text(encoding="utf-8")))
    assert {"name", "description", "body"} <= data.keys()
    body = cast(list[dict[str, object]], data["body"])
    ids = [cast(str, item["id"]) for item in body if item["type"] != "markdown"]
    assert ids
    assert len(ids) == len(set(ids))
    for item in body:
        assert item["type"] in {"markdown", "input", "textarea", "dropdown", "checkboxes"}
        assert "attributes" in item


def test_wheel_ships_the_license(tmp_path: Path) -> None:
    """Integration: build the real wheel and check the licence file and SPDX metadata are inside."""
    uv = VENV_BIN / "uv"
    exe = str(uv) if uv.is_file() else "uv"
    done = subprocess.run(  # noqa: S603 — fixed command, no shell
        [exe, "build", "--wheel", "--out-dir", str(tmp_path), "--quiet", str(ROOT)],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert done.returncode == 0, done.stderr
    (wheel,) = tmp_path.glob("*.whl")
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
        assert any(n.endswith(".dist-info/licenses/LICENSE") for n in names), names
        metadata = zf.read(next(n for n in names if n.endswith(".dist-info/METADATA"))).decode()
    assert "License-Expression: Apache-2.0" in metadata
    assert not any(n.startswith("tests/") for n in names)
