"""[RING:app] Composition root: the one place concrete implementations are chosen and wired.

Why: features depend on base classes, never on backends; something has to pick the backends, and
only `app` may (ADR 0002). It is also the only app module that imports infrastructure: driving
adapters (CLI, UI) call the composers below instead (contract `driving-adapters-use-the-container`).
The fake run wiring is S05; retrieval (S06) is the first live wiring: an httpx client with the
User-Agent and timeouts, and the SQLite cache under `var_dir` in the configured mode (ADR 0009).
`build_models` (S08) resolves each LLM role through the catalogue and checks its provider settings.
Must not: hold logic. It builds objects, composes infrastructure with pure parsers, and normalises
infrastructure errors into the domain's error types.
"""

import hashlib
import time
from collections.abc import Callable, Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx

from bio_claim_check import __version__
from bio_claim_check.app.settings import ENV_PREFIX, Settings
from bio_claim_check.app.usecases.build_corpus import CorpusFiles
from bio_claim_check.app.usecases.run import RunPorts
from bio_claim_check.common.errors import BccError
from bio_claim_check.engine.cache.base_cache import BaseCache
from bio_claim_check.engine.cache.in_memory_cache import InMemoryCache
from bio_claim_check.engine.cache.policy import CacheMode
from bio_claim_check.engine.cache.sqlite_cache import SqliteCache
from bio_claim_check.engine.llm.model_spec import ModelCatalog, ModelSpec, Provider
from bio_claim_check.features.answer.scripted_answerer import ScriptedAnswerer
from bio_claim_check.features.contracts.corpus import (
    CorpusSpec,
    CorpusSpecError,
    CorpusSplit,
    parse_corpus_spec,
)
from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.contracts.rulepack import RulePack, RulePackError, parse_rulepack
from bio_claim_check.features.corpus.layout import MANIFEST, SEALED, audit_file
from bio_claim_check.features.corpus.seal import sealed_bytes
from bio_claim_check.features.report.canonical import REPORT_FILE, canonical_bytes, run_id
from bio_claim_check.features.report.models import Report
from bio_claim_check.features.retrieval.europe_pmc_literature_source import EuropePmcLiteratureSource
from bio_claim_check.features.retrieval.in_memory_literature_source import InMemoryLiteratureSource
from bio_claim_check.features.verify.scripted_verifier import ScriptedVerifier
from bio_claim_check.infrastructure.publish import PublishError, publish_once
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


def load_corpus_spec(path: Path) -> CorpusSpec:
    """The corpus spec from a YAML file; every problem is a `CorpusSpecError` line naming the file."""
    try:
        data = load_strict_yaml(read_text_file(path), str(path))
    except ReadError as err:
        raise CorpusSpecError([str(err)]) from None
    except StrictYamlError as err:
        raise CorpusSpecError(list(err.problems)) from None
    return parse_corpus_spec(data, str(path))


def file_sha256(path: Path) -> str:
    """sha256 of a file's raw bytes (the spec as committed); a read failure is a `CorpusSpecError`."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as err:
        raise CorpusSpecError([f"{path}: cannot read: {err.strerror}"]) from None


class OutputConflictError(BccError):
    """An output file exists with different bytes, or cannot be written; nothing is overwritten."""

    code = "app.output_conflict"


def publish_corpus(out: Path, files: CorpusFiles) -> list[Path]:
    """Publish every data file once, then the manifest last, so a manifest only exists over complete data.

    Every destination (manifest included) is checked before anything is written, so a conflicting old
    file never ends up beside new ones. `publish_once` still refuses a file that appears in between.
    Raises `OutputConflictError` on a conflict or a filesystem error.
    """
    plan = [(Path(name), data) for name, data in sorted(files.data.items())]
    plan.append((Path(MANIFEST), files.manifest))
    try:
        for name, data in plan:
            target = out / name
            if target.exists() and (not target.is_file() or target.read_bytes() != data):
                raise OutputConflictError(f"{target} exists with different content; refusing to overwrite")
        return [publish_once(out.joinpath(*name.parts[:-1]), name.name, data) for name, data in plan]
    except PublishError as err:
        raise OutputConflictError(str(err)) from None
    except OSError as err:
        raise OutputConflictError(f"cannot write the dataset under {out}: {err}") from None


class DatasetReadError(BccError):
    """The dataset folder, or a file in it, cannot be read."""

    code = "app.dataset_read"


def read_dataset(folder: Path) -> dict[str, bytes]:
    """Every file under `folder`, keyed by its POSIX path relative to it, so the seal check sees extras too.

    Only `.DS_Store` (macOS folder metadata) is skipped. Any other hidden file is returned, so the seal
    check reports it as an unexpected file instead of letting it sit beside the data unseen.
    """
    if not folder.is_dir():
        raise DatasetReadError(f"{folder} is not a folder")
    try:
        paths = [p for p in sorted(folder.rglob("*")) if p.is_file()]
        visible = [p for p in paths if p.name != ".DS_Store"]
        return {p.relative_to(folder).as_posix(): p.read_bytes() for p in visible}
    except OSError as err:
        raise DatasetReadError(f"cannot read the dataset under {folder}: {err}") from None


def write_seal(folder: Path, manifest: bytes) -> Path:
    """Write `SEALED` once; the same seal again is a no-op, a different one is an `OutputConflictError`."""
    try:
        return publish_once(folder, SEALED, sealed_bytes(manifest))
    except PublishError as err:
        raise OutputConflictError(str(err)) from None
    except OSError as err:
        raise OutputConflictError(f"cannot write {folder / SEALED}: {err}") from None


def publish_audit(folder: Path, split: CorpusSplit, kind: OverstatedReason, record: bytes) -> Path:
    """Publish one audit record into the dataset once; a different existing record is refused."""
    name = Path(audit_file(split, kind))
    try:
        return publish_once(folder.joinpath(*name.parts[:-1]), name.name, record)
    except PublishError as err:
        raise OutputConflictError(str(err)) from None
    except OSError as err:
        raise OutputConflictError(f"cannot write {folder / name}: {err}") from None


def publish_sheet(out: Path, split: CorpusSplit, kind: OverstatedReason, sheet: str) -> Path:
    """Write an audit sheet (abstract text, so under the git-ignored `var/`) once; never overwrites."""
    try:
        return publish_once(out, f"{split.value}-{kind.value}.csv", sheet.encode())
    except PublishError as err:
        raise OutputConflictError(str(err)) from None
    except OSError as err:
        raise OutputConflictError(f"cannot write the sheet under {out}: {err}") from None


@contextmanager
def build_replay(settings: Settings) -> Generator[EuropePmcLiteratureSource]:
    """`build_retrieval` forced to a read-only cache: a replay never reaches the network."""
    with build_retrieval(settings.model_copy(update={"cache_mode": CacheMode.READ_ONLY})) as source:
        yield source


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
) -> Generator[EuropePmcLiteratureSource]:
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


class MissingProviderError(BccError):
    """A live LLM role whose provider has no settings; the message names the role and the settings."""

    code = "app.missing_provider"


_PROVIDER_SETTINGS: dict[Provider, str] = {
    Provider.FOUNDRY_OPENAI: "foundry",
    Provider.FOUNDRY_ANTHROPIC: "foundry",
    Provider.ANTHROPIC: "anthropic",
    Provider.OLLAMA: "ollama",
}


@dataclass(frozen=True, slots=True)
class RoleModels:
    """The model spec behind each LLM role."""

    answer: ModelSpec
    verifier: ModelSpec
    trap: ModelSpec


def build_models(settings: Settings, catalog: ModelCatalog) -> RoleModels:
    """Each role's spec from the catalogue (an unknown deployment raises `UnknownDeploymentError`).

    Outside `read-only`, a role whose provider is not configured raises `MissingProviderError` naming the
    role, before any call is made. A read-only replay needs no provider: it never reaches one (ADR 0009).
    """
    roles = {
        "answer": catalog.lookup(settings.answer_model),
        "verifier": catalog.lookup(settings.verifier_model),
        "trap": catalog.lookup(settings.trap_model),
    }
    if settings.cache_mode is not CacheMode.READ_ONLY:
        configured = set(settings.configured_providers)
        for role, spec in roles.items():
            needed = _PROVIDER_SETTINGS[spec.provider]
            if needed not in configured:
                raise MissingProviderError(
                    f"the {role} model {spec.deployment!r} needs {needed} settings "
                    f"({ENV_PREFIX}{needed.upper()}__*); use {ENV_PREFIX}CACHE_MODE=read-only to replay"
                )
    return RoleModels(answer=roles["answer"], verifier=roles["verifier"], trap=roles["trap"])
