"""[RING:app] Composition root: the one place concrete implementations are chosen and wired.

Why: features depend on base classes, never on backends; something has to pick the backends, and
only `app` may (ADR 0002). It is also the only app module that imports infrastructure: driving
adapters (CLI, UI) call the composers below instead (contract `driving-adapters-use-the-container`).
The fake run wiring is S05; retrieval (S06) is the first live wiring: an httpx client with the
User-Agent and timeouts, and the SQLite cache under `var_dir` in the configured mode (ADR 0009).
`build_models` (S08) resolves each LLM role through the catalogue and checks its provider settings;
`build_llm_clients` (S09) builds the live provider backends: one SDK client per Foundry API, SDK retries
off (our `transport_policy` retries), URLs derived from the one Foundry resource endpoint.
`build_dev_answer_ports` (S10) wires the live dev answer flow: Europe PMC and the answer model share one
cache in the configured mode, and a read-only replay needs no provider at all. From S11 every live client
sits behind one `CallBudget` per command, inside the cache, and `record_run` wires the run record's file
operations (`app.run_record` holds its logic). `build_live_run_ports` (S12a) wires a live or dev `run`:
Europe PMC, the answerer and the LLM verifier share one cache and one budget (ADR 0019).
`build_challenge_ports` and `current_judge` (S12b) wire the dev challenge run and the judge fingerprint
of the code as installed (ADR 0020).
Must not: hold logic. It builds objects, composes infrastructure with pure parsers, and normalises
infrastructure errors into the domain's error types.
"""

import hashlib
import importlib.metadata
import time
from collections.abc import Callable, Generator, Iterable
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import anthropic
import httpx
import openai
from pydantic import JsonValue

from bio_claim_check import __version__
from bio_claim_check.app.freeze import (
    ACTIVE_FREEZE,
    JUDGE_FILES,
    JudgeInputs,
    freeze_problems,
    freeze_record,
    judge_inputs,
)
from bio_claim_check.app.models import model_catalog
from bio_claim_check.app.run_record import (
    EVENTS_DIR,
    LEDGER_FILE,
    MANIFEST_FILE,
    RUNS_DIR,
    TRACE_SUFFIX,
    DeclaredLlm,
    RecordIo,
    RunRecorder,
    TraceHandle,
    recording,
    trace_stem,
)
from bio_claim_check.app.settings import ENV_PREFIX, Settings
from bio_claim_check.app.usecases.answer_dev import DevAnswerPorts
from bio_claim_check.app.usecases.build_corpus import CorpusFiles
from bio_claim_check.app.usecases.challenge import ChallengePorts
from bio_claim_check.app.usecases.check_claim import CheckPorts
from bio_claim_check.app.usecases.published_run import VIEWABLE_FILES, PublishedRunError
from bio_claim_check.app.usecases.published_run import validate_run_id as validate_published_id
from bio_claim_check.app.usecases.retractions import (
    REPORT_FILE,
    RetractionCheck,
    RetractionInputError,
    validate_run_id,
)
from bio_claim_check.app.usecases.run import RunPorts
from bio_claim_check.app.usecases.traps import TrapWriterPorts
from bio_claim_check.common.base_clock import BaseClock
from bio_claim_check.common.canonical_json import compact_json
from bio_claim_check.common.errors import BccError
from bio_claim_check.common.system_clock import SystemClock
from bio_claim_check.engine.cache.base_cache import BaseCache
from bio_claim_check.engine.cache.in_memory_cache import InMemoryCache
from bio_claim_check.engine.cache.policy import CacheMode
from bio_claim_check.engine.cache.sqlite_cache import SqliteCache
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.errors import EventWriteError
from bio_claim_check.engine.events.in_memory_event_sink import InMemoryEventSink
from bio_claim_check.engine.events.logging_event_sink import LoggingEventSink
from bio_claim_check.engine.events.tee_event_sink import TeeEventSink
from bio_claim_check.engine.llm.anthropic_llm_client import AnthropicLlmClient
from bio_claim_check.engine.llm.base_llm_client import BaseLlmClient
from bio_claim_check.engine.llm.budgeted_llm_client import BudgetedLlmClient, CallBudget
from bio_claim_check.engine.llm.caching_llm_client import CachingLlmClient
from bio_claim_check.engine.llm.model_spec import ModelCatalog, ModelSpec, Provider
from bio_claim_check.engine.llm.openai_llm_client import OpenAiLlmClient
from bio_claim_check.engine.prompts.prompt_template import PromptTemplate
from bio_claim_check.features.answer.llm_answerer import LlmAnswerer
from bio_claim_check.features.answer.over_eager_answer_llm_agent import OverEagerAnswerLlmAgent
from bio_claim_check.features.answer.scripted_answerer import (
    OVER_EAGER_SCRIPT,
    STRICT_SCRIPT,
    ScriptedAnswerer,
)
from bio_claim_check.features.answer.strict_answer_llm_agent import StrictAnswerLlmAgent
from bio_claim_check.features.contracts.corpus import (
    CorpusSpec,
    CorpusSpecError,
    CorpusSplit,
    parse_corpus_spec,
)
from bio_claim_check.features.contracts.labels import AnswerMode, OverstatedReason
from bio_claim_check.features.contracts.rulepack import RulePack, RulePackError, parse_rulepack
from bio_claim_check.features.contracts.verdict import Claim
from bio_claim_check.features.corpus.layout import MANIFEST, SEALED, audit_file
from bio_claim_check.features.corpus.seal import sealed_bytes
from bio_claim_check.features.report.models import ModelUse, RunModels
from bio_claim_check.features.retrieval.europe_pmc_literature_source import EuropePmcLiteratureSource
from bio_claim_check.features.retrieval.in_memory_literature_source import InMemoryLiteratureSource
from bio_claim_check.features.traps.llm_trap_writer import LlmTrapWriter
from bio_claim_check.features.traps.trap_llm_agent import TrapLlmAgent
from bio_claim_check.features.verify.llm_verifier import LlmVerifier
from bio_claim_check.features.verify.scripted_verifier import VERDICT_SCRIPT, ScriptedVerifier
from bio_claim_check.features.verify.verify_llm_agent import VerifyLlmAgent
from bio_claim_check.infrastructure.line_files import AppendError, LineFile, append_line, create_numbered
from bio_claim_check.infrastructure.publish import PublishError, publish_once
from bio_claim_check.infrastructure.strict_yaml import StrictYamlError, load_strict_yaml
from bio_claim_check.infrastructure.text_files import ReadError, read_package_bytes, read_text_file

DEFAULT_RULEPACK = ("data", "rulepacks", "default.yaml")
REPO_URL = "https://github.com/squliyev/bio-claim-check"
CACHE_FILE = "cache.sqlite"
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
LLM_TIMEOUT_S = 300.0  # a long structured answer may take minutes; connecting may not
LLM_CONNECT_TIMEOUT_S = 10.0


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


@dataclass(frozen=True, slots=True)
class HashedRulePack:
    """A parsed rule pack and the sha256 of the exact file bytes it was parsed from (the run manifest)."""

    pack: RulePack
    sha256: str


def default_rulepack_hashed() -> HashedRulePack:
    """The shipped rule pack, read as bytes once: hashed, then decoded and parsed."""
    try:
        data = read_package_bytes(*DEFAULT_RULEPACK)
        text = data.decode("utf-8")
    except ReadError as err:
        raise RulePackError([str(err)]) from None
    except UnicodeDecodeError as err:
        raise RulePackError([f"{DEFAULT_RULEPACK[-1]}: not UTF-8: {err}"]) from None
    return HashedRulePack(_rulepack_from_text(text, DEFAULT_RULEPACK[-1]), hashlib.sha256(data).hexdigest())


def default_rulepack() -> RulePack:
    """The rule pack shipped with the package (author-written seed rules)."""
    return default_rulepack_hashed().pack


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


def publish_document(folder: Path, name: str, data: bytes) -> Path:
    """Write a document once (challenge results, freeze records); different existing bytes are refused."""
    try:
        return publish_once(folder, name, data)
    except PublishError as err:
        raise OutputConflictError(str(err)) from None
    except OSError as err:
        raise OutputConflictError(f"cannot write {folder / name}: {err}") from None


@contextmanager
def build_replay(settings: Settings) -> Generator[EuropePmcLiteratureSource]:
    """`build_retrieval` forced to a read-only cache: a replay never reaches the network."""
    with build_retrieval(settings.model_copy(update={"cache_mode": CacheMode.READ_ONLY})) as source:
        yield source


def _trace_handle(file: LineFile) -> TraceHandle:
    def write_line(data: bytes) -> None:
        file.write_line(data)  # an OSError becomes EventWriteError in JsonlEventSink

    def close() -> None:
        try:
            file.close()
        except OSError as err:
            raise EventWriteError(f"cannot close the trace {file.path.name}: {err.strerror or err}") from None

    return TraceHandle(name=file.path.name, write_line=write_line, close=close)


def record_io(var_dir: Path) -> RecordIo:
    """The run record's file operations under `var_dir`; every failure is typed (`RECORD_OUTPUT_ERRORS`)."""

    def open_trace(stem: str) -> TraceHandle:
        try:
            return _trace_handle(create_numbered(var_dir / EVENTS_DIR, stem, TRACE_SUFFIX))
        except OSError as err:
            raise EventWriteError(f"cannot create a trace under {var_dir / EVENTS_DIR}: {err}") from None

    def publish(run_id: str, name: str, data: bytes) -> None:
        try:
            publish_once(var_dir / RUNS_DIR / run_id, name, data)
        except OSError as err:
            raise PublishError(f"cannot write {var_dir / RUNS_DIR / run_id / name}: {err}") from None

    def append_ledger(line: bytes) -> None:
        append_line(var_dir / LEDGER_FILE, line)

    return RecordIo(open_trace=open_trace, publish=publish, append_ledger=append_ledger)


RECORD_OUTPUT_ERRORS: Final = (EventWriteError, PublishError, AppendError)
"""The run record's output failures (ADR 0018); the CLI maps them to the OUTPUT exit code."""


def record_run(
    var_dir: Path, command: str, cache_mode: CacheMode | None, *, clock: BaseClock | None = None
) -> AbstractContextManager[RunRecorder]:
    """Record one command attempt under `var_dir` (ADR 0018); the wall clock unless one is given."""
    return recording(record_io(var_dir), clock or SystemClock(), command, cache_mode, __version__)


def run_path(var_dir: Path, run_id: str) -> Path:
    """The folder of a published run."""
    return var_dir / RUNS_DIR / run_id


RETRACTIONS_DIR: Final = "retractions"


def read_run_files(var_dir: Path, run_id: str) -> tuple[bytes, bytes]:
    """The manifest and report bytes of a published run; `RetractionInputError` if either is unreadable."""
    folder = run_path(var_dir, validate_run_id(run_id))
    try:
        return (folder / MANIFEST_FILE).read_bytes(), (folder / REPORT_FILE).read_bytes()
    except OSError as err:
        raise RetractionInputError(f"run {run_id}: cannot read {folder}: {err.strerror or err}") from None


def read_published_files(var_dir: Path, run_id: str) -> tuple[bytes, bytes]:
    """The manifest and artifact bytes of a published `run` or `check`; `PublishedRunError` if unreadable.
    The artifact is whichever viewable file the folder holds; `load_published` then checks it is the one
    the manifest names."""
    folder = run_path(var_dir, validate_published_id(run_id))
    present = [name for name in VIEWABLE_FILES if (folder / name).is_file()]
    if len(present) != 1:
        raise PublishedRunError(f"run {run_id}: expected one of {', '.join(VIEWABLE_FILES)} in {folder}")
    try:
        return (folder / MANIFEST_FILE).read_bytes(), (folder / present[0]).read_bytes()
    except OSError as err:
        raise PublishedRunError(f"run {run_id}: cannot read {folder}: {err.strerror or err}") from None


def read_ledger(var_dir: Path) -> bytes:
    """The run ledger's bytes; empty when no command has run yet."""
    try:
        return (var_dir / LEDGER_FILE).read_bytes()
    except FileNotFoundError:
        return b""
    except OSError as err:
        raise PublishedRunError(f"cannot read {var_dir / LEDGER_FILE}: {err.strerror or err}") from None


def publish_retraction_check(var_dir: Path, check: RetractionCheck) -> Path:
    """Write `retractions/<run_id>-<UTC>-<n>.json` (one compact JSON line) by exclusive create, never
    under `runs/`."""
    stem = f"{check.run_id}-{trace_stem(check.checked_at)}"
    try:
        with create_numbered(var_dir / RETRACTIONS_DIR, stem, ".json") as file:
            file.write_line(compact_json(check.model_dump(mode="json")).encode("utf-8"))
            return file.path
    except OSError as err:
        raise PublishError(f"cannot write a retraction check under {var_dir / RETRACTIONS_DIR}: {err}") from (
            None
        )


@contextmanager
def build_retraction_source(settings: Settings) -> Generator[EuropePmcLiteratureSource]:
    """Europe PMC with the cache off: the re-check always asks the database (ADR 0019)."""
    with build_retrieval(settings.model_copy(update={"cache_mode": CacheMode.OFF})) as source:
        yield source


def build_fake_run_ports(emitter: EventEmitter | None = None) -> RunPorts:
    """Fictional papers, scripted answers and verdicts. Needs no settings, network or `.env`."""
    rules = default_rulepack_hashed()
    return RunPorts(
        literature=InMemoryLiteratureSource(),
        answerer=ScriptedAnswerer(),
        verifier=ScriptedVerifier(),
        rules=rules.pack,
        provenance="fake",
        rules_sha256=rules.sha256,
        emitter=emitter,
    )


def _cache(settings: Settings, stack: ExitStack) -> BaseCache:
    if settings.cache_mode is CacheMode.OFF:
        return InMemoryCache()  # never read or written in this mode; no file is created
    read_only = settings.cache_mode is CacheMode.READ_ONLY
    return stack.enter_context(SqliteCache(settings.var_dir / CACHE_FILE, read_only=read_only))


def fake_check_claims() -> tuple[Claim, ...]:
    """The fictional claims a fake check can take: every scripted one-paper claim with a scripted verdict."""
    return tuple(
        c
        for c in (*STRICT_SCRIPT, *OVER_EAGER_SCRIPT)
        if len(c.cites) == 1 and (c.id, c.cites[0]) in VERDICT_SCRIPT
    )


def build_fake_check_ports(emitter: EventEmitter | None = None) -> CheckPorts:
    """Fictional papers and scripted verdicts for `check --fake`. Needs no settings, network or `.env`."""
    rules = default_rulepack_hashed()
    return CheckPorts(
        literature=InMemoryLiteratureSource(),
        verifier=ScriptedVerifier(),
        rules=rules.pack,
        provenance="fake",
        rules_sha256=rules.sha256,
        emitter=emitter,
    )


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
        yield _europe_pmc(settings, stack, _cache(settings, stack), transport, sleep)


def _europe_pmc(
    settings: Settings,
    stack: ExitStack,
    cache: BaseCache,
    transport: httpx.BaseTransport | None,
    sleep: Callable[[float], None],
) -> EuropePmcLiteratureSource:
    client = stack.enter_context(
        httpx.Client(
            transport=transport,
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": user_agent(settings)},
            follow_redirects=False,
        )
    )
    return EuropePmcLiteratureSource(client, cache, settings.cache_mode, sleep=sleep)


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


class UnsupportedProviderError(BccError):
    """A deployment whose provider has no adapter yet (S09 adapts Foundry's OpenAI and Anthropic APIs)."""

    code = "app.unsupported_provider"


def logging_emitter() -> EventEmitter:
    """Pipeline events to the log (stderr), stamped by the wall clock: the live default until S11's jsonl."""
    return EventEmitter(LoggingEventSink(), SystemClock())


def tallying_emitter() -> tuple[EventEmitter, InMemoryEventSink]:
    """`logging_emitter` that also keeps the events, so a command can print its LLM usage at the end."""
    kept = InMemoryEventSink()
    return EventEmitter(TeeEventSink(LoggingEventSink(), kept), SystemClock()), kept


def foundry_urls(base_url: str) -> tuple[str, str]:
    """The `/openai/v1/` and `/anthropic` endpoints of one Foundry resource (same endpoint and key)."""
    root = base_url.rstrip("/")
    return f"{root}/openai/v1/", f"{root}/anthropic"


@contextmanager
def build_llm_clients(
    settings: Settings,
    specs: Iterable[ModelSpec],
    *,
    sleep: Callable[[float], None] = time.sleep,
    emitter: EventEmitter | None = None,
    openai_http: openai.DefaultHttpxClient | None = None,
    anthropic_http: anthropic.DefaultHttpxClient | None = None,
) -> Generator[dict[str, BaseLlmClient]]:
    """A live backend per deployment in `specs`. Closes the SDK clients on exit.

    Raises `MissingProviderError` without Foundry settings and `UnsupportedProviderError` for a provider
    with no adapter, both before any client is built. `openai_http`/`anthropic_http` are for tests (the
    SDKs' own client class over a mock transport); production uses the SDKs' defaults.
    """
    specs = tuple(specs)
    for spec in specs:
        if spec.provider not in {Provider.FOUNDRY_OPENAI, Provider.FOUNDRY_ANTHROPIC}:
            raise UnsupportedProviderError(
                f"deployment {spec.deployment!r} uses provider {spec.provider.value}, which has no adapter"
            )
    if specs and settings.foundry is None:
        raise MissingProviderError(
            f"deployments {[s.deployment for s in specs]} need foundry settings ({ENV_PREFIX}FOUNDRY__*)"
        )
    with ExitStack() as stack:
        if settings.foundry is None or not specs:
            yield {}
            return
        openai_url, anthropic_url = foundry_urls(str(settings.foundry.base_url))
        key = settings.foundry.api_key.get_secret_value()
        timeout = LLM_TIMEOUT_S, LLM_CONNECT_TIMEOUT_S
        providers = {spec.provider for spec in specs}
        backends: dict[Provider, BaseLlmClient] = {}
        if Provider.FOUNDRY_OPENAI in providers:
            gpt = openai.OpenAI(
                base_url=openai_url,
                api_key=key,
                max_retries=0,
                timeout=openai.Timeout(timeout[0], connect=timeout[1]),
                http_client=openai_http,
            )
            stack.callback(gpt.close)
            backends[Provider.FOUNDRY_OPENAI] = OpenAiLlmClient(gpt, sleep=sleep, emitter=emitter)
        if Provider.FOUNDRY_ANTHROPIC in providers:
            claude = anthropic.AnthropicFoundry(
                base_url=anthropic_url,
                api_key=key,
                max_retries=0,
                timeout=anthropic.Timeout(timeout[0], connect=timeout[1]),
                http_client=anthropic_http,
            )
            stack.callback(claude.close)
            backends[Provider.FOUNDRY_ANTHROPIC] = AnthropicLlmClient(claude, sleep=sleep, emitter=emitter)
        yield {spec.deployment: backends[spec.provider] for spec in specs}


def build_answerer(client: BaseLlmClient, spec: ModelSpec, emitter: EventEmitter | None) -> LlmAnswerer:
    """The LLM answerer: the Strict and the Over-eager agent on one client and one model spec."""
    return LlmAnswerer(
        StrictAnswerLlmAgent(client, spec, emitter=emitter),
        OverEagerAnswerLlmAgent(client, spec, emitter=emitter),
    )


@contextmanager
def build_dev_answer_ports(
    settings: Settings,
    spec: ModelSpec,
    emitter: EventEmitter | None,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    openai_http: openai.DefaultHttpxClient | None = None,
) -> Generator[DevAnswerPorts]:
    """Europe PMC and the answer model through one cache in the configured mode.

    A read-only replay builds no provider client (it never reaches one). Otherwise the provider client
    is built as for `llm ping`, so missing settings raise before any call. `transport`/`openai_http` are
    for tests.
    """
    with ExitStack() as stack:
        cache = _cache(settings, stack)
        source = _europe_pmc(settings, stack, cache, transport, sleep)
        live: BaseLlmClient | None = None
        if settings.cache_mode is not CacheMode.READ_ONLY:
            clients = stack.enter_context(
                build_llm_clients(settings, [spec], sleep=sleep, emitter=emitter, openai_http=openai_http)
            )
            live = BudgetedLlmClient(clients[spec.deployment], CallBudget(settings.max_live_llm_calls))
        client = CachingLlmClient(live, cache, settings.cache_mode)
        yield DevAnswerPorts(source=source, answerer=build_answerer(client, spec, emitter), emitter=emitter)


@dataclass(frozen=True, slots=True)
class LiveRun:
    """The ports of a live or dev `run`, and the LLM roles it declares in its manifest (I71)."""

    ports: RunPorts
    declared_llm: tuple[DeclaredLlm, ...]


def _declared(agent: str, prompt: PromptTemplate, spec: ModelSpec) -> DeclaredLlm:
    return DeclaredLlm(
        agent=agent,
        provider=spec.provider.value,
        deployment=spec.deployment,
        model_version=spec.model_version,
        prompt_sha256=prompt.sha256,
    )


def declared_answerer(spec: ModelSpec, mode: AnswerMode) -> DeclaredLlm:
    """The answer role a live command declares: the agent of `mode` on `spec` (I71)."""
    agent = StrictAnswerLlmAgent if mode is AnswerMode.STRICT else OverEagerAnswerLlmAgent
    return _declared(agent.name, agent.prompt, spec)


def _model_use(spec: ModelSpec) -> ModelUse:
    return ModelUse(deployment=spec.deployment, family=spec.family)


@contextmanager
def build_live_run_ports(
    settings: Settings,
    mode: AnswerMode,
    emitter: EventEmitter | None,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    openai_http: openai.DefaultHttpxClient | None = None,
    anthropic_http: anthropic.DefaultHttpxClient | None = None,
) -> Generator[LiveRun]:
    """Europe PMC, the answerer (`answer_model`) and the LLM verifier (`verifier_model`) through one
    cache in the configured mode, every live client behind one shared `CallBudget` (ADR 0018, 0019).

    A read-only replay builds no provider client. `transport`/`*_http` are for tests.
    """
    roles = build_models(settings, model_catalog())
    answer, verifier = roles.answer, roles.verifier
    rules = default_rulepack_hashed()
    with ExitStack() as stack:
        cache = _cache(settings, stack)
        source = _europe_pmc(settings, stack, cache, transport, sleep)
        budget = CallBudget(settings.max_live_llm_calls)
        live: dict[str, BaseLlmClient | None] = {answer.deployment: None, verifier.deployment: None}
        if settings.cache_mode is not CacheMode.READ_ONLY:
            clients = stack.enter_context(
                build_llm_clients(
                    settings,
                    [answer, verifier],
                    sleep=sleep,
                    emitter=emitter,
                    openai_http=openai_http,
                    anthropic_http=anthropic_http,
                )
            )
            live = {name: BudgetedLlmClient(client, budget) for name, client in clients.items()}
        answer_client = CachingLlmClient(live[answer.deployment], cache, settings.cache_mode)
        verifier_client = CachingLlmClient(live[verifier.deployment], cache, settings.cache_mode)
        ports = RunPorts(
            literature=source,
            answerer=build_answerer(answer_client, answer, emitter),
            verifier=LlmVerifier(VerifyLlmAgent(verifier_client, verifier, emitter=emitter)),
            rules=rules.pack,
            provenance="live",
            rules_sha256=rules.sha256,
            models=RunModels(answerer=_model_use(answer), verifier=_model_use(verifier)),
            emitter=emitter,
        )
        declared = (
            declared_answerer(answer, mode),
            _declared(VerifyLlmAgent.name, VerifyLlmAgent.prompt, verifier),
        )
        yield LiveRun(ports=ports, declared_llm=tuple(sorted(declared, key=lambda d: d.agent)))


@dataclass(frozen=True, slots=True)
class LiveCheck:
    """The ports of a live `check`, and the one LLM role it declares in its manifest (I71)."""

    ports: CheckPorts
    declared_llm: tuple[DeclaredLlm, ...]


@contextmanager
def build_live_check_ports(
    settings: Settings,
    emitter: EventEmitter | None,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    openai_http: openai.DefaultHttpxClient | None = None,
    anthropic_http: anthropic.DefaultHttpxClient | None = None,
) -> Generator[LiveCheck]:
    """Europe PMC and the LLM verifier (`verifier_model`) through one cache, behind one `CallBudget`: the
    verifier role of `build_live_run_ports`, without an answerer (ADR 0025).

    A read-only replay builds no provider client. `transport`/`*_http` are for tests.
    """
    verifier = build_models(settings, model_catalog()).verifier
    rules = default_rulepack_hashed()
    with ExitStack() as stack:
        cache = _cache(settings, stack)
        source = _europe_pmc(settings, stack, cache, transport, sleep)
        live: BaseLlmClient | None = None
        if settings.cache_mode is not CacheMode.READ_ONLY:
            clients = stack.enter_context(
                build_llm_clients(
                    settings,
                    [verifier],
                    sleep=sleep,
                    emitter=emitter,
                    openai_http=openai_http,
                    anthropic_http=anthropic_http,
                )
            )
            live = BudgetedLlmClient(clients[verifier.deployment], CallBudget(settings.max_live_llm_calls))
        client = CachingLlmClient(live, cache, settings.cache_mode)
        ports = CheckPorts(
            literature=source,
            verifier=LlmVerifier(VerifyLlmAgent(client, verifier, emitter=emitter)),
            rules=rules.pack,
            provenance="live",
            rules_sha256=rules.sha256,
            verifier_model=_model_use(verifier),
            emitter=emitter,
        )
        yield LiveCheck(
            ports=ports, declared_llm=(_declared(VerifyLlmAgent.name, VerifyLlmAgent.prompt, verifier),)
        )


class JudgeReadError(BccError):
    """A judge file is missing from the installed package."""

    code = "app.judge_read"


def _spec_json(spec: ModelSpec) -> dict[str, JsonValue]:
    return spec.model_dump(mode="json", exclude={"price"})


def current_judge(settings: Settings) -> JudgeInputs:
    """The judge fingerprint of this installation with the configured answer and verifier models."""
    roles = build_models(settings.model_copy(update={"cache_mode": CacheMode.READ_ONLY}), model_catalog())
    try:
        files = {name: read_package_bytes(*name.split("/")) for name in JUDGE_FILES}
    except ReadError as err:
        raise JudgeReadError(str(err)) from None
    return judge_inputs(
        files, importlib.metadata.version("rapidfuzz"), _spec_json(roles.answer), _spec_json(roles.verifier)
    )


class FreezeError(BccError):
    """This code is not the active frozen judge, so the test split stays closed (ADR 0020, I74)."""

    code = "app.freeze"

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = tuple(problems)


def active_freeze_sha256(settings: Settings, freeze_dir: Path, challenge_result: Path) -> str:
    """Recompute the active freeze from this code and the committed files; refuse unless it still holds."""
    try:
        committed = (freeze_dir / f"{ACTIVE_FREEZE}.json").read_bytes()
        result = challenge_result.read_bytes()
    except OSError as err:
        raise FreezeError([f"cannot read the active freeze: {err.strerror or type(err).__name__}"]) from None
    try:
        current = freeze_record(ACTIVE_FREEZE, current_judge(settings), result)
    except JudgeReadError as err:
        raise FreezeError([str(err)]) from None
    if problems := freeze_problems(committed, current):
        raise FreezeError(problems)
    return current.freeze_sha256


@contextmanager
def build_challenge_ports(
    settings: Settings,
    emitter: EventEmitter | None,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    anthropic_http: anthropic.DefaultHttpxClient | None = None,
    openai_http: openai.DefaultHttpxClient | None = None,
) -> Generator[tuple[ChallengePorts, ModelSpec]]:
    """Europe PMC and the LLM verifier through one cache in the configured mode, behind one budget.

    A read-only replay builds no provider client. `transport`/`*_http` are for tests.
    """
    verifier = build_models(settings, model_catalog()).verifier
    rules = default_rulepack_hashed()
    with ExitStack() as stack:
        cache = _cache(settings, stack)
        source = _europe_pmc(settings, stack, cache, transport, sleep)
        live: BaseLlmClient | None = None
        if settings.cache_mode is not CacheMode.READ_ONLY:
            clients = stack.enter_context(
                build_llm_clients(
                    settings,
                    [verifier],
                    sleep=sleep,
                    emitter=emitter,
                    openai_http=openai_http,
                    anthropic_http=anthropic_http,
                )
            )
            live = BudgetedLlmClient(clients[verifier.deployment], CallBudget(settings.max_live_llm_calls))
        client = CachingLlmClient(live, cache, settings.cache_mode)
        ports = ChallengePorts(
            literature=source,
            verifier=LlmVerifier(VerifyLlmAgent(client, verifier, emitter=emitter)),
            rules=rules.pack,
            emitter=emitter,
        )
        yield ports, verifier


@contextmanager
def build_trap_ports(
    settings: Settings,
    emitter: EventEmitter | None,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    anthropic_http: anthropic.DefaultHttpxClient | None = None,
    openai_http: openai.DefaultHttpxClient | None = None,
) -> Generator[tuple[TrapWriterPorts, ModelSpec]]:
    """Europe PMC and the LLM trap writer (the trap role) through one cache, behind one budget.

    A read-only replay builds no provider client. `transport`/`*_http` are for tests.
    """
    writer = build_models(settings, model_catalog()).trap
    with ExitStack() as stack:
        cache = _cache(settings, stack)
        source = _europe_pmc(settings, stack, cache, transport, sleep)
        live: BaseLlmClient | None = None
        if settings.cache_mode is not CacheMode.READ_ONLY:
            clients = stack.enter_context(
                build_llm_clients(
                    settings,
                    [writer],
                    sleep=sleep,
                    emitter=emitter,
                    openai_http=openai_http,
                    anthropic_http=anthropic_http,
                )
            )
            live = BudgetedLlmClient(clients[writer.deployment], CallBudget(settings.max_live_llm_calls))
        client = CachingLlmClient(live, cache, settings.cache_mode)
        ports = TrapWriterPorts(
            literature=source,
            writer=LlmTrapWriter(TrapLlmAgent(client, writer, emitter=emitter)),
            rules=default_rulepack_hashed().pack,
            emitter=emitter,
        )
        yield ports, writer
