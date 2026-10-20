"""Residual guards: proven on synthetic input first, then run over the real repository."""

import importlib
import sys
from pathlib import Path, PurePosixPath

import grimp
import pytest

from tests.support.guards import (
    PACKAGE_NAME,
    check_adr_fields,
    check_no_ancestor_imports,
    check_ring_header,
    check_test_support_header,
    check_verdict_construction,
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


# ---------------------------------------------------------------- ancestor imports (cycle gap)


class _Graph:
    def __init__(self, edges: dict[str, set[str]]) -> None:
        self._edges = edges

    @property
    def modules(self) -> set[str]:
        return set(self._edges) | {m for targets in self._edges.values() for m in targets}

    def find_modules_directly_imported_by(self, module: str) -> set[str]:
        return self._edges.get(module, set())


@pytest.mark.parametrize(
    "edges",
    [
        {"pkg.a.child": {"pkg.a"}},  # child imports its parent package (re-export loop)
        {"pkg.a.b.c": {"pkg.a"}},  # grandchild imports a grandparent
        {"pkg": {"pkg.a"}},  # the root package imports something internal
    ],
)
def test_ancestor_guard_rejects(edges: dict[str, set[str]]) -> None:
    assert len(check_no_ancestor_imports(_Graph(edges), "pkg")) == 1


@pytest.mark.parametrize(
    "edges",
    [
        {"pkg.a.child": {"pkg"}},  # reading the root (e.g. __version__) is fine
        {"pkg.a": {"pkg.a.child"}},  # a package importing its own child is fine
        {"pkg.a.child": {"pkg.b", "pydantic"}},  # sibling packages and externals are not ancestors
        {"pkg.ab.x": {"pkg.a"}},  # name prefix is not ancestry
        {"pkg": {"importlib"}},  # the root may import externals
    ],
)
def test_ancestor_guard_accepts(edges: dict[str, set[str]]) -> None:
    assert check_no_ancestor_imports(_Graph(edges), "pkg") == []


def test_ancestor_guard_catches_a_real_reexport_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end with grimp: the exact cycle shape that import-linter's acyclic_siblings misses."""
    pkg = tmp_path / "cyclepkg" / "verify"
    pkg.mkdir(parents=True)
    (tmp_path / "cyclepkg" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("from cyclepkg.verify.svc import f\n", encoding="utf-8")
    (pkg / "svc.py").write_text("from cyclepkg.verify import g\n", encoding="utf-8")
    monkeypatch.setattr(sys, "path", [str(tmp_path), *sys.path])
    importlib.invalidate_caches()
    found = check_no_ancestor_imports(grimp.build_graph("cyclepkg", cache_dir=None), "cyclepkg")
    assert [v.detail.split(":")[0] for v in found] == ["cyclepkg.verify.svc -> cyclepkg.verify"]


def test_the_real_package_has_no_ancestor_imports() -> None:
    graph = grimp.build_graph(PACKAGE_NAME, cache_dir=None)
    assert len(list(graph.modules)) > 1  # discovered something
    assert check_no_ancestor_imports(graph, PACKAGE_NAME) == []


def _verdict(text: str, rel: str = "bio_claim_check/features/verify/x.py") -> list[str]:
    return [v.detail for v in check_verdict_construction(Path(rel), text, src_relative=PurePosixPath(rel))]


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("Verdict(claim_id='c')\n", id="direct"),
        pytest.param("contracts.verdict.Verdict(claim_id='c')\n", id="qualified"),
        pytest.param("Verdict.model_construct(claim_id='c')\n", id="model-construct"),
        pytest.param("verdict.Verdict.model_construct()\n", id="qualified-model-construct"),
        pytest.param("from bio_claim_check.features.contracts.verdict import Verdict as V\n", id="alias"),
        pytest.param("V = Verdict\n", id="assignment-alias"),
        pytest.param("V: type = verdict.Verdict\n", id="annotated-alias"),
        pytest.param("getattr(Verdict, 'model_construct')()\n", id="getattr"),
        pytest.param("BaseModel.model_copy(v, update={'negation': 'clear'})\n", id="base-model-copy"),
    ],
)
def test_verdict_guard_rejects(text: str) -> None:
    assert len(_verdict(text)) == 1


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("Verdict.finalise(c, s, out, abstract)\n", id="finalise"),
        pytest.param("Verdict.model_validate(data)\n", id="model-validate"),
        pytest.param("from bio_claim_check.features.contracts.verdict import Verdict\n", id="plain-import"),
        pytest.param("Other.model_construct()\nx = Verdict.finalise\n", id="other-model"),
        pytest.param("v.model_copy()\ngetattr(v, 'reason')\n", id="plain-copy-and-getattr"),
        pytest.param("# Verdict(x)\ns = 'Verdict(x)'\n", id="comment-and-string"),
    ],
)
def test_verdict_guard_accepts(text: str) -> None:
    assert _verdict(text) == []


def test_verdict_guard_exempts_only_its_home() -> None:
    assert _verdict("Verdict(x)\n", "bio_claim_check/features/contracts/verdict.py") == []
    assert _verdict("Verdict(x)\n", "bio_claim_check/features/contracts/other.py")


def test_no_verdict_is_constructed_outside_its_home() -> None:
    files = sorted(SRC.rglob("*.py"))
    assert any(
        f.relative_to(SRC).as_posix() == "bio_claim_check/features/contracts/verdict.py" for f in files
    )
    found = [
        v
        for f in files
        for v in check_verdict_construction(
            f, f.read_text(encoding="utf-8"), src_relative=PurePosixPath(f.relative_to(SRC).as_posix())
        )
    ]
    assert found == []
