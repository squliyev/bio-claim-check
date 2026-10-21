"""`bio-claim-check retrieve` end to end through the container, with Europe PMC scripted (no network)."""

import contextlib
from collections.abc import Generator
from pathlib import Path

import httpx
import pytest
from tests.support.europepmc import Reply, ScriptedServer, envelope, mixed_records, ok
from typer.testing import CliRunner

from bio_claim_check import __version__
from bio_claim_check.app import cli
from bio_claim_check.app.container import CACHE_FILE, build_retrieval
from bio_claim_check.app.settings import Settings
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource

pytestmark = pytest.mark.unit
runner = CliRunner()
EMAIL = "someone@example.org"


@pytest.fixture
def var_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("BCC_CONTACT_EMAIL", EMAIL)
    monkeypatch.setenv("BCC_VAR_DIR", str(tmp_path / "var"))
    return tmp_path / "var"


def serve(monkeypatch: pytest.MonkeyPatch, *replies: Reply) -> ScriptedServer:
    """Route the CLI's container through a scripted server; retries never really sleep."""
    server = ScriptedServer(list(replies))

    @contextlib.contextmanager
    def scripted(settings: Settings) -> Generator[BaseLiteratureSource]:
        with build_retrieval(settings, transport=server.transport(), sleep=lambda _: None) as source:
            yield source

    monkeypatch.setattr(cli, "build_retrieval", scripted)
    return server


def mixed() -> httpx.Response:
    return ok(envelope(mixed_records()))


def retrieve(*args: str) -> tuple[int, str, str]:
    result = runner.invoke(cli.app, ["retrieve", *args])
    return result.exit_code, result.stdout, result.stderr


def test_prints_citable_papers_and_flags_retractions(var_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server = serve(monkeypatch, mixed())
    code, out, err = retrieve("aspirin", "--k", "25")
    assert code == 0, err
    assert out.startswith("5 citable paper(s) from Europe PMC (MEDLINE/PubMed-indexed abstracts)\n")
    assert "retraction status is as of the first fetch" in out
    assert out.count("[RETRACTED]") == 2
    assert "MED:90000009 (n.d.)" in out
    assert (var_dir / CACHE_FILE).is_file()
    assert server.requests[0].headers["User-Agent"] == (
        f"bio-claim-check/{__version__} (+https://github.com/squliyev/bio-claim-check; mailto:{EMAIL})"
    )


def test_second_run_is_served_from_the_cache(var_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, mixed())
    first = retrieve("aspirin")
    server = serve(monkeypatch)  # any request now fails the test
    assert retrieve("aspirin") == first
    assert server.requests == []


def test_read_only_replays_and_never_writes(var_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, mixed())
    first = retrieve("aspirin")
    before = (var_dir / CACHE_FILE).read_bytes()
    monkeypatch.setenv("BCC_CACHE_MODE", "read-only")
    serve(monkeypatch)
    assert retrieve("aspirin") == first
    assert (var_dir / CACHE_FILE).read_bytes() == before


def test_read_only_miss_exits_3_without_a_request(var_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BCC_CACHE_MODE", "read-only")
    server = serve(monkeypatch)
    code, out, err = retrieve("aspirin")
    assert (code, out) == (3, "")
    assert "read-only" in err
    assert server.requests == []
    assert not var_dir.exists()  # read-only never creates the cache


def test_off_mode_fetches_every_time_and_creates_no_file(
    var_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BCC_CACHE_MODE", "off")
    server = serve(monkeypatch, mixed(), mixed())
    assert retrieve("aspirin")[0] == 0
    assert retrieve("aspirin")[0] == 0
    assert len(server.requests) == 2
    assert not var_dir.exists()


@pytest.mark.parametrize("args", [["   "], ["aspirin", "--k", "0"], ["aspirin", "--k", "101"]])
def test_bad_input_exits_2_before_any_request(
    var_dir: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    server = serve(monkeypatch)
    code, _, err = retrieve(*args)
    assert code == 2
    assert err.count("\n") == 1  # one line, no traceback
    assert server.requests == []


def test_missing_contact_email_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    server = serve(monkeypatch)
    code, _, err = retrieve("aspirin")
    assert code == 2
    assert "contact_email" in err
    assert server.requests == []


def test_upstream_failure_exits_4_and_caches_nothing(var_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, httpx.Response(400, text="bad query"))
    code, out, err = retrieve("aspirin")
    assert (code, out) == (4, "")
    assert err.startswith("retrieval failed: ")
    assert EMAIL not in err
    serve(monkeypatch, mixed())  # the failure was not cached: a retry reaches the server
    assert retrieve("aspirin")[0] == 0


def test_unreadable_cache_file_exits_5(var_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    var_dir.mkdir()
    (var_dir / CACHE_FILE).write_bytes(b"this is not a sqlite database" * 100)
    server = serve(monkeypatch)
    code, _, err = retrieve("aspirin")
    assert code == 5
    assert err.startswith("cache problem: ")
    assert server.requests == []


def test_an_undecodable_env_file_exits_2_without_echoing_it(tmp_path: Path) -> None:
    env = tmp_path / "bad.env"
    env.write_bytes(b"BCC_CONTACT_EMAIL=\xff\xfe secret\n")
    result = runner.invoke(cli.app, ["retrieve", "aspirin", "--env-file", str(env)])
    assert result.exit_code == 2
    assert result.stderr == f"Cannot read {env}: UnicodeDecodeError\n"
