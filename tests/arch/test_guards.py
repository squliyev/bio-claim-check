"""Residual guards: proven on synthetic input first, then run over the real repository."""

from pathlib import Path, PurePosixPath

import pytest

from tests.support.guards import (
    check_adr_fields,
    check_ring_header,
    check_test_support_header,
    expected_ring,
)
from tests.support.paths import ADR_DIR, ROOT, SRC

pytestmark = pytest.mark.arch

ADR_OK = "# ADR 0001 — X\n- **Status:** Accepted\n- **Date:** 2026-10-20\n- **Enforced by:** ruff TID251\n"


# ---------------------------------------------------------------- ring header: synthetic


@pytest.mark.parametrize(
    ("path", "ring"),
    [
        ("bio_claim_check/__init__.py", "root"),
        ("bio_claim_check/app/settings.py", "app"),
        ("bio_claim_check/app/__init__.py", "app"),
        ("bio_claim_check/app/cli/__init__.py", "app/cli"),
        ("bio_claim_check/features/bench/stats.py", "features/bench"),
        ("bio_claim_check/features/verify/__init__.py", "features/verify"),
        ("bio_claim_check/engine/llm/__init__.py", "engine/llm"),
    ],
)
def test_expected_ring_mapping(path: str, ring: str) -> None:
    assert expected_ring(PurePosixPath(path)) == ring


def test_expected_ring_rejects_paths_outside_the_package() -> None:
    with pytest.raises(ValueError, match="not inside"):
        expected_ring(PurePosixPath("other/x.py"))


def _ring(text: str, rel: str = "bio_claim_check/common/x.py") -> list[str]:
    return [v.detail for v in check_ring_header(Path(rel), text, src_relative=PurePosixPath(rel))]


def test_ring_header_accepts_matching_tag() -> None:
    assert _ring('"""[RING:common] Why this exists."""\n') == []


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("x = 1\n", "missing module docstring"),
        ('"""No tag."""\n', "must start with [RING:common]"),
        ('"""[RING:engine] wrong ring"""\n', "expected common"),
        ("# [RING:common] in a comment is not a docstring\nx = 1\n", "missing module docstring"),
    ],
)
def test_ring_header_rejects(text: str, fragment: str) -> None:
    assert any(fragment in d for d in _ring(text))


# ---------------------------------------------------------------- test-support header: synthetic


def test_test_support_header_accepts_and_rejects() -> None:
    assert check_test_support_header(Path("s.py"), '"""[TEST SUPPORT] builders."""\n') == []
    assert check_test_support_header(Path("s.py"), '"""Builders."""\n')
    assert check_test_support_header(Path("s.py"), "x = 1\n")


# ---------------------------------------------------------------- ADR fields: synthetic


def test_adr_fields_accepts_a_complete_header() -> None:
    assert check_adr_fields(Path("0001-x.md"), ADR_OK) == []


@pytest.mark.parametrize(
    ("broken", "field"),
    [
        (ADR_OK.replace("- **Enforced by:** ruff TID251\n", ""), "Enforced by"),
        (ADR_OK.replace("2026-10-20", "<date>"), "Date"),
        (ADR_OK.replace("Accepted", "Maybe"), "Status"),
    ],
)
def test_adr_fields_rejects(broken: str, field: str) -> None:
    assert [v.detail for v in check_adr_fields(Path("0001-x.md"), broken)] == [
        f"missing or malformed '- **{field}:**' line"
    ]


# ---------------------------------------------------------------- the real repository


def test_every_source_module_has_a_correct_ring_header() -> None:
    files = sorted(SRC.rglob("*.py"))
    assert files, "no source files discovered: did src/ move?"
    violations = [
        v
        for f in files
        for v in check_ring_header(
            f, f.read_text(encoding="utf-8"), src_relative=PurePosixPath(f.relative_to(SRC).as_posix())
        )
    ]
    assert violations == []


def test_every_test_support_module_is_tagged() -> None:
    files = sorted((ROOT / "tests" / "support").glob("*.py"))
    assert files
    assert [v for f in files for v in check_test_support_header(f, f.read_text(encoding="utf-8"))] == []


def test_every_adr_has_status_date_and_enforced_by() -> None:
    files = sorted(ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"))
    assert files, "no ADRs discovered"
    assert [v for f in files for v in check_adr_fields(f, f.read_text(encoding="utf-8"))] == []
