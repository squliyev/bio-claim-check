"""[RING:app] Composition root: the one place concrete implementations are chosen and wired.

Why: features depend on base classes, never on backends; something has to pick the backends, and
only `app` may (ADR 0002). It is also the only app module that imports infrastructure: driving
adapters (CLI, UI) call the composers below instead (contract `driving-adapters-use-the-container`).
The fake run wiring is S05; retrieval (S06) is the first live wiring: an httpx client with the
User-Agent and timeouts, and the SQLite cache under `var_dir` in the configured mode (ADR 0009).
Must not: hold logic. It builds objects, composes infrastructure with pure parsers, and normalises
infrastructure errors into the domain's error types.
"""

import time
from collections.abc import Callable, Generator
from contextlib import ExitStack, contextmanager
from pathlib import Path

import httpx

from bio_claim_check import __version__
from bio_claim_check.app.settings import Settings
from bio_claim_check.app.usecases.run import RunPorts
from bio_claim_check.engine.cache.base_cache import BaseCache
from bio_claim_check.engine.cache.in_memory_cache import InMemoryCache
from bio_claim_check.engine.cache.policy import CacheMode
from bio_claim_check.engine.cache.sqlite_cache import SqliteCache
from bio_claim_check.features.answer.scripted_answerer import ScriptedAnswerer
from bio_claim_check.features.contracts.rulepack import RulePack, RulePackError, parse_rulepack
from bio_claim_check.features.report.canonical import REPORT_FILE, canonical_bytes, run_id
from bio_claim_check.features.report.models import Report
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.retrieval.europe_pmc_literature_source import EuropePmcLiteratureSource
from bio_claim_check.features.retrieval.in_memory_literature_source import InMemoryLiteratureSource
from bio_claim_check.features.verify.scripted_verifier import ScriptedVerifier
from bio_claim_check.infrastructure.publish import publish_once
from bio_claim_check.infrastructure.strict_yaml import StrictYamlError, load_strict_yaml
from bio_claim_check.infrastructure.text_files import ReadError, read_package_text, read_text_file

DEFAULT_RULEPACK = ("data", "rulepacks", "default.yaml")
REPO_URL = "https://github.com/squliyev/bio-claim-check"
CACHE_FILE = "cache.sqlite"
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def user_agent(settings: Settings) -> str:
    """Europe PMC etiquette: name the tool and give a contact address (ADR 0008)."""
    return f"bio-claim-check/{__version__} (+{REPO_URL}; mailto:{settings.contact_email})"


def _rulepack_from_text(text: str, source: str) -> RulePack:
    try:
        data = load_strict_yaml(text, source)
    except StrictYamlError as err:
        raise RulePackError(list(err.problems)) from None
    return parse_rulepack(data, source)


def load_rulepack(path: Path) -> RulePack:
    """A rule pack from a YAML file; every problem is a `RulePackError` line naming the file."""
    try:
        text = read_text_file(path)
    except ReadError as err:
        raise RulePackError([str(err)]) from None
    return _rulepack_from_text(text, str(path))


def default_rulepack() -> RulePack:
    """The rule pack shipped with the package (author-written seed rules)."""
    try:
        text = read_package_text(*DEFAULT_RULEPACK)
    except ReadError as err:
        raise RulePackError([str(err)]) from None
    return _rulepack_from_text(text, DEFAULT_RULEPACK[-1])


def publish_report(out: Path, report: Report) -> Path:
    """Write `<out>/<run_id>/report.json` once, as canonical bytes, and return its path."""
    data = canonical_bytes(report)
    return publish_once(out / run_id(data), REPORT_FILE, data)


def build_fake_run_ports() -> RunPorts:
    """Fictional papers, scripted answers and verdicts. Needs no settings, network or `.env`."""
    return RunPorts(
        literature=InMemoryLiteratureSource(),
        answerer=ScriptedAnswerer(),
        verifier=ScriptedVerifier(),
        rules=default_rulepack(),
        provenance="fake",
    )


def _cache(settings: Settings, stack: ExitStack) -> BaseCache:
    if settings.cache_mode is CacheMode.OFF:
        return InMemoryCache()  # never read or written in this mode; no file is created
    read_only = settings.cache_mode is CacheMode.READ_ONLY
    return stack.enter_context(SqliteCache(settings.var_dir / CACHE_FILE, read_only=read_only))


@contextmanager
def build_retrieval(
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Generator[BaseLiteratureSource]:
    """Europe PMC through the cache at `<var_dir>/cache.sqlite`. Closes the client and the cache on exit.

    `transport` is for tests (an `httpx.MockTransport`); production uses httpx's default.
    """
    with ExitStack() as stack:
        cache = _cache(settings, stack)
        client = stack.enter_context(
            httpx.Client(
                transport=transport,
                timeout=HTTP_TIMEOUT,
                headers={"User-Agent": user_agent(settings)},
                follow_redirects=False,
            )
        )
        yield EuropePmcLiteratureSource(client, cache, settings.cache_mode, sleep=sleep)
