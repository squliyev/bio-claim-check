"""`bio-claim-check corpus build`: files, notice and every exit code, with a fictional literature source."""

import contextlib
from collections.abc import Callable, Generator
from pathlib import Path
from typing import override

import pytest
from tests.support.corpus import SPEC_FILE, QueryLiteratureSource, world
from tests.support.papers import paper
from typer.testing import CliRunner

from bio_claim_check.app import cli
from bio_claim_check.app.settings import Settings
from bio_claim_check.engine.cache.policy import CacheError, CacheMissError
from bio_claim_check.features.contracts.corpus import NLM_NOTICE, CorpusManifest
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.corpus.layout import DEV_SOURCES, MANIFEST, QUESTIONS, TEST_SOURCES
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.retrieval.errors import RetrievalError

pytestmark = pytest.mark.unit
runner = CliRunner()
DATA_FILES = (DEV_SOURCES, QUESTIONS, TEST_SOURCES)


class RaisingSource(BaseLiteratureSource):
    def __init__(self, error: Exception) -> None:
        self._error = error

    @override
    def search(self, question: str, *, limit: int) -> tuple[Paper, ...]:
        raise self._error

    def response_sha256(self, question: str, limit: int) -> str:
        """Never reached: `search` raises first. Present because the CLI reads it like the real source."""
        raise AssertionError((question, limit))


@pytest.fixture(autouse=True)
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BCC_CONTACT_EMAIL", "someone@example.org")
    monkeypatch.setenv("BCC_VAR_DIR", str(tmp_path / "var"))


def use(monkeypatch: pytest.MonkeyPatch, make: Callable[[], BaseLiteratureSource]) -> None:
    @contextlib.contextmanager
    def scripted(settings: Settings) -> Generator[BaseLiteratureSource]:
        yield make()

    monkeypatch.setattr(cli, "build_retrieval", scripted)


def build(out: Path, *args: str, spec: Path = SPEC_FILE, day: str = "2025-01-15") -> tuple[int, str, str]:
    argv = ["corpus", "build", "--spec", str(spec), "--declared-fetched-on", day, "--out", str(out), *args]
    result = runner.invoke(cli.app, argv)
    return result.exit_code, result.stdout, result.stderr


def test_writes_every_file_and_prints_the_notice_and_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, lambda: QueryLiteratureSource(world()))
    out = tmp_path / "datasets"
    code, stdout, stderr = build(out)
    assert code == 0, stderr
    lines = stdout.splitlines()
    assert lines[0] == NLM_NOTICE
    assert lines[1:5] == [f"wrote: {out / name}" for name in (*DATA_FILES, MANIFEST)]
    assert lines[5] == "candidates (domain, split, kind: n):"
    manifest = CorpusManifest.model_validate_json((out / MANIFEST).read_bytes())
    assert lines[6:] == [
        f"  {c.domain} {c.split.value} {c.kind.value}: {c.n}" for c in manifest.candidate_counts
    ]
    assert any(c.n > 0 for c in manifest.candidate_counts)
    assert all((out / name).is_file() for name in (*DATA_FILES, MANIFEST))


def test_a_rebuild_is_identical_and_a_no_op(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, lambda: QueryLiteratureSource(world()))
    out = tmp_path / "datasets"
    first = build(out)
    before = {name: (out / name).read_bytes() for name in (*DATA_FILES, MANIFEST)}
    assert build(out) == first
    assert {name: (out / name).read_bytes() for name in before} == before


def test_a_different_existing_file_exits_6_and_the_manifest_is_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, lambda: QueryLiteratureSource(world()))
    out = tmp_path / "datasets"
    (out / "test").mkdir(parents=True)
    (out / TEST_SOURCES).write_bytes(b"something else\n")
    code, _, stderr = build(out)
    assert code == cli.ExitCode.OUTPUT
    assert "Traceback" not in stderr
    assert (out / TEST_SOURCES).read_bytes() == b"something else\n"
    assert not (out / MANIFEST).exists()


def test_an_output_path_that_is_a_file_exits_6(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, lambda: QueryLiteratureSource(world()))
    out = tmp_path / "datasets"
    out.write_bytes(b"a file\n")
    code, _, stderr = build(out)
    assert code == cli.ExitCode.OUTPUT
    assert "Traceback" not in stderr


def test_a_different_declared_date_cannot_overwrite_a_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, lambda: QueryLiteratureSource(world()))
    out = tmp_path / "datasets"
    assert build(out)[0] == 0
    before = (out / MANIFEST).read_bytes()
    assert build(out, day="2025-02-01")[0] == cli.ExitCode.OUTPUT
    assert (out / MANIFEST).read_bytes() == before


@pytest.mark.parametrize("day", ["15/01/2025", "2025-1-5x", "", "20250115", "2025-W03-3", "2025-02-30"])
def test_a_bad_date_exits_2_before_any_retrieval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, day: str
) -> None:
    use(monkeypatch, lambda: pytest.fail("retrieval must not start"))
    code, _, stderr = build(tmp_path / "datasets", day=day)
    assert code == cli.ExitCode.INPUT
    assert "--declared-fetched-on must be YYYY-MM-DD" in stderr


def test_an_invalid_spec_exits_2_and_lists_each_problem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, lambda: pytest.fail("retrieval must not start"))
    spec = tmp_path / "spec.yaml"
    spec.write_text(SPEC_FILE.read_text(encoding="utf-8").replace("audit_n: 50", "audit_n: 0\nextra: 1"))
    code, _, stderr = build(tmp_path / "datasets", spec=spec)
    assert code == cli.ExitCode.INPUT
    assert stderr.startswith("Invalid corpus spec (2 problem(s)):\n")
    assert "audit_n" in stderr
    assert "extra" in stderr
    assert not (tmp_path / "datasets").exists()


def test_a_missing_spec_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, lambda: pytest.fail("retrieval must not start"))
    code, _, stderr = build(tmp_path / "datasets", spec=tmp_path / "missing.yaml")
    assert code == cli.ExitCode.INPUT
    assert "Invalid corpus spec (1 problem(s)):" in stderr


@pytest.mark.parametrize(
    ("make", "exit_code", "message"),
    [
        (lambda: RaisingSource(CacheMissError("k")), cli.ExitCode.CACHE_MISS, "BCC_CACHE_MODE=read-only"),
        (
            lambda: RaisingSource(RetrievalError("HTTP 500")),
            cli.ExitCode.UPSTREAM,
            "retrieval failed: HTTP 500",
        ),
        (lambda: RaisingSource(CacheError("locked")), cli.ExitCode.LOCAL_CACHE, "cache problem: locked"),
        (lambda: RaisingSource(ValueError("blank question")), cli.ExitCode.INPUT, "blank question"),
    ],
    ids=["cache-miss", "upstream", "local-cache", "input"],
)
def test_retrieval_failures_map_to_exit_codes_and_write_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    make: Callable[[], BaseLiteratureSource],
    exit_code: int,
    message: str,
) -> None:
    use(monkeypatch, make)
    out = tmp_path / "datasets"
    code, _, stderr = build(out)
    assert code == exit_code
    assert message in stderr
    assert "Traceback" not in stderr
    assert not out.exists()


def test_a_pool_conflict_exits_4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pools = world()
    _, second, _ = pools
    pools[second] = (*pools[second][:-1], paper(1, mesh=("Humans",)))  # ANIMAL (MED:1), changed metadata
    use(monkeypatch, lambda: QueryLiteratureSource(pools))
    code, _, stderr = build(tmp_path / "datasets")
    assert code == cli.ExitCode.UPSTREAM
    assert "MED:1 differs between two questions' results" in stderr
