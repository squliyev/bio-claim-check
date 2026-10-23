"""[RING:app/cli] Command-line driving adapter — the primary interface.

The CLI parses arguments, calls the composition root and renders results. It holds no business logic:
anything worth testing lives in ``features`` or ``app.usecases`` and is called from here. It reaches
infrastructure only through ``app.container`` (contract ``driving-adapters-use-the-container``).
"""

import hashlib
import re
from collections import Counter
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import date
from enum import IntEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from bio_claim_check import __version__
from bio_claim_check.app.container import (
    RECORD_OUTPUT_ERRORS,
    DatasetReadError,
    JudgeReadError,
    MissingProviderError,
    OutputConflictError,
    UnsupportedProviderError,
    build_challenge_ports,
    build_dev_answer_ports,
    build_fake_run_ports,
    build_live_run_ports,
    build_llm_clients,
    build_replay,
    build_retraction_source,
    build_retrieval,
    current_judge,
    declared_answerer,
    default_rulepack,
    file_sha256,
    load_corpus_spec,
    load_rulepack,
    logging_emitter,
    publish_audit,
    publish_corpus,
    publish_document,
    publish_retraction_check,
    publish_sheet,
    read_dataset,
    read_run_files,
    record_run,
    run_path,
    write_seal,
)
from bio_claim_check.app.freeze import FREEZE_DIR, freeze_record
from bio_claim_check.app.logging_setup import configure_logging
from bio_claim_check.app.models import model_catalog
from bio_claim_check.app.run_record import RunDetails, RunInputs, RunRecorder
from bio_claim_check.app.settings import ENV_PREFIX, Settings, load_settings
from bio_claim_check.app.usecases.answer_dev import (
    DevAnswer,
    DevAnswerInputError,
    DevDatasetError,
    EmptyDevPoolError,
    answer_dev,
    dev_answer_record,
)
from bio_claim_check.app.usecases.build_corpus import PoolConflictError, build_corpus
from bio_claim_check.app.usecases.challenge import (
    ChallengeInputError,
    ChallengePoolError,
    ChallengeResult,
    attestation_problems,
    result_bytes,
    run_challenge,
)
from bio_claim_check.app.usecases.corpus_audit import (
    AUDIT_SPLIT,
    AuditInputError,
    apply_decisions,
    export_sheet,
)
from bio_claim_check.app.usecases.llm_ping import PingResult, ping
from bio_claim_check.app.usecases.retractions import (
    RetractionCheck,
    RetractionInputError,
    cited_ids,
    load_checked_run,
    retraction_check,
)
from bio_claim_check.app.usecases.run import RunInputError, run_question
from bio_claim_check.app.usecases.run_dev import DevRunRecord, run_dev
from bio_claim_check.common.canonical_json import pretty_json_bytes
from bio_claim_check.common.negation import NEGATION_RULES
from bio_claim_check.common.system_clock import SystemClock
from bio_claim_check.engine.cache.policy import CacheError, CacheMissError
from bio_claim_check.engine.events.call_tally import summed, tally_calls
from bio_claim_check.engine.events.pipeline_event import PipelineEvent
from bio_claim_check.engine.llm.errors import (
    LlmBudgetExceededError,
    LlmCallError,
    LlmPromptFilteredError,
    LlmProviderError,
    LlmRequestError,
    LlmTransportError,
    LlmUnexpectedResponseError,
)
from bio_claim_check.engine.llm.model_spec import UnknownDeploymentError
from bio_claim_check.features.answer.answer_models import AnswerClaimsError
from bio_claim_check.features.contracts.corpus import CorpusManifest, CorpusSpec, CorpusSpecError
from bio_claim_check.features.contracts.finding import FindingKind
from bio_claim_check.features.contracts.labels import AnswerMode, OverstatedReason
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.rulepack import RulePack, RulePackError
from bio_claim_check.features.corpus.audit_sheet import AuditSheetError
from bio_claim_check.features.corpus.layout import MANIFEST, SEALED, SPEC
from bio_claim_check.features.corpus.seal import dataset_problems
from bio_claim_check.features.report.canonical import REPORT_FILE, canonical_bytes
from bio_claim_check.features.report.models import Report
from bio_claim_check.features.retrieval.errors import RetrievalError

DEFAULT_K = 4
DEFAULT_RETRIEVE_K = 10


class ExitCode(IntEnum):
    """Process exit codes; the curated table is docs/error-codes.md (a parity test keeps them in step)."""

    INPUT = 2  # bad arguments or configuration
    CACHE_MISS = 3  # read-only cache mode and the request is not cached
    UPSTREAM = 4  # the literature database failed
    LOCAL_CACHE = 5  # the cache file cannot be opened, read or written
    OUTPUT = 6  # an output file exists with different bytes or cannot be written (nothing is overwritten)
    DATASET = 7  # the dataset is not intact (seal, hashes, splits, counts, audits), or a dev pool is empty
    PROVIDER = 8  # an LLM call failed or returned an unusable answer (its error code is printed)


_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")  # date.fromisoformat also takes 20250115 and 2025-W03-3
DEFAULT_VAR_DIR = Path("var")  # relative to the working directory; --fake never reads settings
ANSWER_FILE = "answer.json"

app = typer.Typer(
    name="bio-claim-check",
    help="Does this agent's answer hold up? Check life-science claims against the abstracts they cite.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,  # never dump locals (which may hold secrets) in tracebacks
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"bio-claim-check {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_print_version, is_eager=True, help="Show the version and exit."),
    ] = False,
) -> None:
    """Root command group."""


EnvFile = Annotated[Path, typer.Option(help="Dotenv file to read in addition to the environment.")]
DatasetDir = Annotated[Path, typer.Option("--dataset", help="Dataset folder holding corpus.yaml.")]


def _settings(env_file: Path) -> Settings:
    """Validated settings, or every problem on stderr (never the offending values) and exit 2.

    Logging is configured here, right after settings load and before any command composes its ports,
    so every command that reads settings logs the same way; settings-free commands (`run --fake`,
    `rulepack validate`, `corpus verify`) keep stdlib's default (warnings and above, to stderr).
    """
    try:
        settings = load_settings(env_file if env_file.exists() else None)
    except ValidationError as err:
        typer.echo(f"Invalid configuration ({err.error_count()} problem(s)):", err=True)
        for problem in err.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in problem["loc"]) or "settings"
            typer.echo(f"  - {location}: {problem['msg']}", err=True)
        raise typer.Exit(code=ExitCode.INPUT) from None
    except (OSError, UnicodeDecodeError) as err:
        typer.echo(f"Cannot read {env_file}: {type(err).__name__}", err=True)
        raise typer.Exit(code=ExitCode.INPUT) from None
    configure_logging(settings)
    return settings


@app.command("config")
def show_config(env_file: EnvFile = Path(".env")) -> None:
    """Validate configuration and print it with secrets redacted."""
    settings = _settings(env_file)
    typer.echo(settings.model_dump_json(indent=2))
    typer.echo(f"providers: {', '.join(settings.configured_providers) or 'none'}")


rulepack_app = typer.Typer(help="Inspect and validate rule packs.", no_args_is_help=True)
app.add_typer(rulepack_app, name="rulepack")


@rulepack_app.command("validate")
def validate_rulepack(
    path: Annotated[
        Path | None,
        typer.Argument(help="Rule-pack YAML file. Defaults to the pack shipped with the package."),
    ] = None,
) -> None:
    """Validate a rule pack and summarise what it covers and who reviewed it."""
    try:
        pack = default_rulepack() if path is None else load_rulepack(path)
    except RulePackError as err:
        typer.echo(f"Invalid rule pack ({len(err.problems)} problem(s)):", err=True)
        for problem in err.problems:
            typer.echo(f"  - {problem}", err=True)
        raise typer.Exit(code=ExitCode.INPUT) from None
    _print_summary(pack)


def _print_summary(pack: RulePack) -> None:
    examples = [example for rule in pack.rules for example in rule.examples]
    reviewed = sum(1 for example in examples if example.reviewed_by)
    typer.echo(f"rule pack {pack.version} (schema {pack.schema_version}) by {', '.join(pack.authors)}")
    typer.echo(f"rules: {len(pack.rules)}")
    for rule in pack.rules:
        typer.echo(f"  - {rule.id} ({rule.reason.value}): {len(rule.examples)} example(s)")
    typer.echo(f"examples: {len(examples)} ({len(examples) - reviewed} author-written, {reviewed} reviewed)")


@app.command("run")
def run(
    question: Annotated[
        str, typer.Argument(help="The research question to answer and check; with --dev, a dev question id.")
    ],
    fake: Annotated[
        bool, typer.Option("--fake", help="Fictional papers, scripted answer and verdicts (offline demo).")
    ] = False,
    dev: Annotated[
        bool, typer.Option("--dev", help="QUESTION is a dev question id; answer from its sealed dev pool.")
    ] = False,
    mode: Annotated[AnswerMode, typer.Option(help="How the answering agent behaves.")] = AnswerMode.STRICT,
    k: Annotated[int, typer.Option("--k", min=1, help="Number of papers to answer from.")] = DEFAULT_K,
    var_dir: Annotated[
        Path | None,
        typer.Option(
            "--var-dir", help="--fake only: root for runs/, events/ and ledger.jsonl [default: var]."
        ),
    ] = None,
    dataset: Annotated[
        Path | None, typer.Option("--dataset", help="--dev only: dataset folder [default: datasets].")
    ] = None,
    env_file: Annotated[
        Path | None, typer.Option(help="Live and --dev: dotenv file to read [default: .env].")
    ] = None,
) -> None:
    """Answer a question, check every claim against the paper it cites, and record the run.

    Live and --dev runs cost tokens and use the var dir from settings (one root for the cache and the
    record); --fake is offline and reads no settings.
    """
    if problem := _run_flag_problem(fake=fake, dev=dev, var_dir=var_dir, dataset=dataset, env_file=env_file):
        _fail(ExitCode.INPUT, problem)
    if fake:
        _run_fake(question, mode, k, var_dir or DEFAULT_VAR_DIR)
    else:
        _run_live(question, mode, k, dev=dev, dataset=dataset or Path("datasets"), env_file=env_file)


def _run_flag_problem(
    *, fake: bool, dev: bool, var_dir: Path | None, dataset: Path | None, env_file: Path | None
) -> str | None:
    if fake and dev:
        return "--fake and --dev cannot be combined"
    if fake and (dataset is not None or env_file is not None):
        return "--fake reads no dataset or settings; drop --dataset and --env-file"
    if not fake and var_dir is not None:
        return f"--var-dir is for --fake; live runs use {ENV_PREFIX}VAR_DIR (one root for cache and record)"
    if not dev and dataset is not None:
        return "--dataset is for --dev"
    return None


def _run_fake(question: str, mode: AnswerMode, k: int, var_dir: Path) -> None:
    try:
        with record_run(var_dir, "run", None) as recorder:
            ports = build_fake_run_ports(recorder.emitter)
            report = run_question(ports, question, mode, k=k)
            details = RunDetails(
                provenance=ports.provenance,
                inputs=RunInputs(question_sha256=_sha256(question), mode=mode, k=k),
                negation_rules=NEGATION_RULES,
                rulepack_sha256=ports.rules_sha256,
            )
            recorder.prepare(REPORT_FILE, canonical_bytes(report), details)
    except RunInputError as err:
        _fail(ExitCode.INPUT, str(err))
    except RECORD_OUTPUT_ERRORS as err:
        _fail(ExitCode.OUTPUT, str(err))
    _print_report(report, _run_file(var_dir, recorder, REPORT_FILE))


def _run_live(
    question: str, mode: AnswerMode, k: int, *, dev: bool, dataset: Path, env_file: Path | None
) -> None:
    settings = _settings(env_file or Path(".env"))
    recorder: RunRecorder | None = None
    dev_record: DevRunRecord | None = None
    try:
        with _live_exit_codes(dataset), record_run(settings.var_dir, "run", settings.cache_mode) as recorder:
            files = read_dataset(dataset) if dev else None
            spec = load_corpus_spec(dataset / SPEC) if dev else None
            with build_live_run_ports(settings, mode, recorder.emitter) as live:
                if files is not None and spec is not None:
                    dev_record = run_dev(live.ports, files, spec, question, mode, k=k)
                    report = dev_record.report
                    artifact = pretty_json_bytes(dev_record.model_dump(mode="json"))
                else:
                    report = run_question(live.ports, question, mode, k=k)
                    artifact = canonical_bytes(report)
            details = RunDetails(
                provenance="live",
                inputs=(
                    RunInputs(question_id=question, mode=mode, k=k)
                    if dev
                    else RunInputs(question_sha256=_sha256(question), mode=mode, k=k)
                ),
                negation_rules=NEGATION_RULES,
                rulepack_sha256=live.ports.rules_sha256,
                dataset_manifest_sha256=_sha256(files[MANIFEST]) if files is not None else None,
                declared_llm=live.declared_llm,
            )
            recorder.prepare(REPORT_FILE, artifact, details)
    finally:
        if recorder is not None:
            _print_usage(recorder.events)
    if dev_record is not None:
        dropped = ", ".join(f"{r.value}={n}" for r, n in dev_record.dropped.items() if n) or "none"
        typer.echo(f"{dev_record.question_id}: {len(dev_record.papers)} dev paper(s); dropped: {dropped}")
    _print_report(report, _run_file(settings.var_dir, recorder, REPORT_FILE))


def _print_report(report: Report, path: Path) -> None:
    typer.echo(report.notice)
    if report.models is not None:
        a, v = report.models.answerer, report.models.verifier
        typer.echo(f"models: answerer={a.deployment} ({a.family}), verifier={v.deployment} ({v.family})")
        if report.models.same_family:
            typer.echo(
                f"warning: answerer and verifier are both {a.family} models (not independent)", err=True
            )
    typer.echo(f"report: {path}")
    for name, counts in (("pairs", report.pair_counts), ("claims", report.claim_counts)):
        typer.echo(f"{name}: " + ", ".join(f"{d.value}={n}" for d, n in counts.items()))
    # Claim-level findings are not folded into the dispositions above, so they are always shown beside them.
    kinds = Counter(f.kind for f in report.findings)
    typer.echo("findings: " + ", ".join(f"{kind.value}={kinds[kind]}" for kind in FindingKind))


@contextmanager
def _live_exit_codes(dataset: Path) -> Generator[None]:
    """The exit code of every typed failure of a live command (`answer dev`, `run` live and --dev)."""
    try:
        yield
    except (DatasetReadError, RunInputError) as err:
        _fail(ExitCode.INPUT, str(err))
    except CorpusSpecError as err:
        _print_problems("Invalid corpus spec", err.problems)
        raise typer.Exit(code=ExitCode.INPUT) from None
    except DevDatasetError as err:
        _print_problems(f"{dataset} is not intact", err.problems)
        raise typer.Exit(code=ExitCode.DATASET) from None
    except DevAnswerInputError as err:
        _print_problems("Cannot answer", err.problems)
        raise typer.Exit(code=ExitCode.INPUT) from None
    except (UnknownDeploymentError, MissingProviderError, UnsupportedProviderError) as err:
        _fail(ExitCode.INPUT, str(err))
    except EmptyDevPoolError as err:
        _fail(ExitCode.DATASET, str(err))
    except CacheMissError:
        _fail(ExitCode.CACHE_MISS, "not in the cache and BCC_CACHE_MODE=read-only; run once with read-write")
    except RetrievalError as err:
        _fail(ExitCode.UPSTREAM, f"retrieval failed: {err}")
    except CacheError as err:
        _fail(ExitCode.LOCAL_CACHE, f"cache problem: {err}")
    except (
        LlmCallError,
        LlmTransportError,
        LlmProviderError,
        LlmPromptFilteredError,
        LlmRequestError,
        LlmUnexpectedResponseError,
        LlmBudgetExceededError,
        AnswerClaimsError,
    ) as err:
        _fail(ExitCode.PROVIDER, f"{err.code}: {err}")
    except RECORD_OUTPUT_ERRORS as err:
        _fail(ExitCode.OUTPUT, str(err))


@app.command("retrieve")
def retrieve(
    query: Annotated[str, typer.Argument(help="Europe PMC query, sent verbatim (search syntax allowed).")],
    k: Annotated[int, typer.Option("--k", help="Maximum number of papers (1-100).")] = DEFAULT_RETRIEVE_K,
    env_file: EnvFile = Path(".env"),
) -> None:
    """Search Europe PMC for citable MEDLINE abstracts, through the local cache."""
    settings = _settings(env_file)
    try:
        with build_retrieval(settings) as source:
            papers = source.search(query, limit=k)
    except ValueError as err:
        _fail(ExitCode.INPUT, str(err))
    except CacheMissError:
        _fail(ExitCode.CACHE_MISS, "not in the cache and BCC_CACHE_MODE=read-only; run once with read-write")
    except RetrievalError as err:
        _fail(ExitCode.UPSTREAM, f"retrieval failed: {err}")
    except CacheError as err:
        _fail(ExitCode.LOCAL_CACHE, f"cache problem: {err}")
    typer.echo(f"{len(papers)} citable paper(s) from Europe PMC (MEDLINE/PubMed-indexed abstracts)")
    typer.echo("retraction status is as of the first fetch (cached snapshot)")
    for rank, paper in enumerate(papers, start=1):
        _print_paper(rank, paper)


@app.command("retractions")
def retractions_command(
    run_id: Annotated[str, typer.Argument(help="The id of a recorded live `run` (16 hex characters).")],
    env_file: EnvFile = Path(".env"),
) -> None:
    """Re-check, uncached, whether the papers a recorded live run cited have been retracted since."""
    settings = _settings(env_file)
    try:
        manifest, artifact = read_run_files(settings.var_dir, run_id)
        report = load_checked_run(manifest, artifact, run_id)
        with build_retraction_source(settings) as source:
            statuses = source.retraction_status(cited_ids(report))
        check = retraction_check(report, statuses, run_id, SystemClock().now())
        path = publish_retraction_check(settings.var_dir, check)
    except RetractionInputError as err:
        _fail(ExitCode.INPUT, str(err))
    except RetrievalError as err:
        _fail(ExitCode.UPSTREAM, f"retrieval failed: {err}")
    except RECORD_OUTPUT_ERRORS as err:
        _fail(ExitCode.OUTPUT, str(err))
    _print_retractions(check, path)


def _print_retractions(check: RetractionCheck, path: Path) -> None:
    def shown(value: bool | None, missing: str) -> str:
        return missing if value is None else ("retracted" if value else "not retracted")

    typer.echo(f"{len(check.papers)} cited paper(s) of run {check.run_id}, re-checked uncached")
    for row in check.papers:
        then = shown(row.retracted_in_run, "not retrieved")
        now = shown(row.retracted_now, "not found")
        changed = (
            "  CHANGED"
            if None not in (row.retracted_in_run, row.retracted_now)
            and row.retracted_in_run != row.retracted_now
            else ""
        )
        typer.echo(f"  {row.source_id}: in run {then}; now {now}{changed}")
    typer.echo(f"check: {path}")


llm_app = typer.Typer(help="Check the LLM providers (S09).", no_args_is_help=True)
app.add_typer(llm_app, name="llm")


@llm_app.command("ping")
def llm_ping(
    deployments: Annotated[
        list[str] | None,
        typer.Argument(help="Deployments to ping. Defaults to the answer and verifier role deployments."),
    ] = None,
    env_file: EnvFile = Path(".env"),
) -> None:
    """One tiny fictional structured call per deployment, bypassing the cache. Costs a few tokens."""
    settings = _settings(env_file)
    names = list(dict.fromkeys(deployments or [settings.answer_model, settings.verifier_model]))
    try:
        specs = [model_catalog().lookup(name) for name in names]
        with build_llm_clients(settings, specs) as clients:
            results = ping(clients, specs, emitter=logging_emitter())
    except (UnknownDeploymentError, MissingProviderError, UnsupportedProviderError) as err:
        _fail(ExitCode.INPUT, str(err))
    for result in results:
        _print_ping(result)
    if not all(r.ok for r in results):
        raise typer.Exit(code=ExitCode.PROVIDER)


def _print_ping(result: PingResult) -> None:
    head = f"{result.deployment} (pinned {result.model_version})"
    if not result.ok:
        typer.echo(f"FAIL {head}: {result.error_code}")
        return
    usage = result.usage
    tokens = (
        "usage unknown"
        if usage is None
        else f"in={usage.input_tokens} out={usage.output_tokens} reasoning={usage.reasoning_tokens} "
        f"cached={usage.cached_input_tokens}"
    )
    finish = result.finish.value if result.finish else "?"
    typer.echo(
        f"ok   {head}: served={result.served_model} finish={finish} attempts={result.attempts} {tokens}"
    )


answer_app = typer.Typer(help="Answer dev questions live, to tune the prompts (S10).", no_args_is_help=True)
app.add_typer(answer_app, name="answer")


@answer_app.command("dev")
def answer_dev_command(
    question_id: Annotated[str, typer.Argument(help="A dev question id from the sealed dataset.")],
    mode: Annotated[AnswerMode, typer.Option(help="How the answering agent behaves.")] = AnswerMode.STRICT,
    k: Annotated[int, typer.Option("--k", min=1, help="Maximum number of dev papers to answer from.")] = 8,
    dataset: DatasetDir = Path("datasets"),
    env_file: EnvFile = Path(".env"),
) -> None:
    """Answer one dev question from its sealed dev pool and run the deterministic checks. Costs tokens.

    Records the attempt under the var dir: runs/<run_id>/answer.json and manifest.json on success, an
    event trace, and one ledger row whatever happens (ADR 0018).
    """
    settings = _settings(env_file)
    recorder: RunRecorder | None = None
    try:
        with (
            _live_exit_codes(dataset),
            record_run(settings.var_dir, "answer dev", settings.cache_mode) as recorder,
        ):
            files = read_dataset(dataset)
            spec = load_corpus_spec(dataset / SPEC)
            model = model_catalog().lookup(settings.answer_model)
            with build_dev_answer_ports(settings, model, recorder.emitter) as ports:
                result = answer_dev(ports, files, spec, question_id, mode, k=k)
            details = RunDetails(
                provenance="live",
                inputs=RunInputs(question_id=question_id, mode=mode, k=k),
                negation_rules=NEGATION_RULES,
                dataset_manifest_sha256=_sha256(files[MANIFEST]),
                declared_llm=(declared_answerer(model, mode),),
            )
            record = pretty_json_bytes(dev_answer_record(result, k).model_dump(mode="json"))
            recorder.prepare(ANSWER_FILE, record, details)
    finally:
        if recorder is not None:
            _print_usage(recorder.events)
    _print_dev_answer(result, k)
    typer.echo(f"run: {_run_file(settings.var_dir, recorder, ANSWER_FILE)}")


def _sha256(data: str | bytes) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _run_file(var_dir: Path, recorder: RunRecorder | None, name: str) -> Path:
    if recorder is None or recorder.run_id is None:
        raise AssertionError("a run that returned normally is published")  # pragma: no cover
    return run_path(var_dir, recorder.run_id) / name


def _print_dev_answer(result: DevAnswer, k: int) -> None:
    pool = result.pool
    dropped = ", ".join(f"{reason.value}={n}" for reason, n in pool.dropped.items()) or "none"
    typer.echo(
        f"{result.question.id} ({result.answer.mode.value}): {len(pool.papers)} paper(s); dropped: {dropped}"
    )
    if pool.usable < k:
        typer.echo(f"warning: only {pool.usable} usable dev paper(s), fewer than k={k}", err=True)
    if not result.answer.claims:
        typer.echo("abstained: no claims")
    for claim in result.answer.claims:
        typer.echo(f"  {claim.id} [{', '.join(claim.cites)}] {claim.text}")
    typer.echo(f"findings: {len(result.findings)}")
    for finding in result.findings:
        typer.echo(f"  {finding.kind.value} {finding.claim_id}: {finding.detail}")


def _print_usage(events: Sequence[PipelineEvent]) -> None:
    t = summed(tally_calls(events).values())
    typer.echo(
        f"llm calls: finished_live={t.finished_live_attempts} cache_hit={t.cache_hits} "
        f"failed={t.failed_calls}; "
        f"live tokens in={t.measured_input_tokens} out={t.measured_output_tokens} "
        f"reasoning={t.measured_reasoning_tokens} (unreported on {t.reasoning_unreported} call(s)); "
        f"unmeasured: attempts={t.unmeasured_attempts} transport_retries={t.transport_retries} "
        "(may be billed, usage unknown); money: unpriced",
        err=True,
    )


corpus_app = typer.Typer(help="Build the evaluation corpus (ADR 0010).", no_args_is_help=True)
app.add_typer(corpus_app, name="corpus")


@corpus_app.command("build")
def build_corpus_command(
    spec: Annotated[Path, typer.Option("--spec", help="Corpus spec YAML (questions and constants).")],
    declared_fetched_on: Annotated[
        str, typer.Option("--declared-fetched-on", help="Date the pools were fetched, YYYY-MM-DD.")
    ],
    out: Annotated[Path, typer.Option(help="Dataset folder (dev/, test/, questions, manifest).")] = Path(
        "datasets"
    ),
    env_file: EnvFile = Path(".env"),
) -> None:
    """Fetch every question's pool through the cache, sieve, cluster, split and publish the dataset.

    Rebuilds with BCC_CACHE_MODE=read-only are byte-identical; existing files are never overwritten.
    """
    try:
        if not _ISO_DAY.fullmatch(declared_fetched_on):
            raise ValueError(declared_fetched_on)
        fetched_on = date.fromisoformat(declared_fetched_on)
    except ValueError:
        _fail(ExitCode.INPUT, f"--declared-fetched-on must be YYYY-MM-DD, got {declared_fetched_on!r}")
    try:
        corpus_spec = load_corpus_spec(spec)
        spec_sha = file_sha256(spec)
    except CorpusSpecError as err:
        typer.echo(f"Invalid corpus spec ({len(err.problems)} problem(s)):", err=True)
        for problem in err.problems:
            typer.echo(f"  - {problem}", err=True)
        raise typer.Exit(code=ExitCode.INPUT) from None
    settings = _settings(env_file)
    try:
        with build_retrieval(settings) as source:
            files = build_corpus(
                corpus_spec,
                source,
                declared_fetched_on=fetched_on,
                tool_version=__version__,
                spec_file_sha256=spec_sha,
                response_sha256=source.response_sha256,
            )
        paths = publish_corpus(out, files)
    except ValueError as err:
        _fail(ExitCode.INPUT, str(err))
    except CacheMissError:
        _fail(ExitCode.CACHE_MISS, "not in the cache and BCC_CACHE_MODE=read-only; run once with read-write")
    except (RetrievalError, PoolConflictError) as err:
        _fail(ExitCode.UPSTREAM, f"retrieval failed: {err}")
    except CacheError as err:
        _fail(ExitCode.LOCAL_CACHE, f"cache problem: {err}")
    except OutputConflictError as err:
        _fail(ExitCode.OUTPUT, str(err))
    manifest = CorpusManifest.model_validate_json(files.manifest)
    typer.echo(manifest.notice)
    for path in paths:
        typer.echo(f"wrote: {path}")
    typer.echo("candidates (domain, split, kind: n):")
    for c in manifest.candidate_counts:
        typer.echo(f"  {c.domain} {c.split.value} {c.kind.value}: {c.n}")


def _dataset(folder: Path) -> tuple[dict[str, bytes], CorpusSpec]:
    try:
        files = read_dataset(folder)
        spec = load_corpus_spec(folder / SPEC)
    except DatasetReadError as err:
        _fail(ExitCode.INPUT, str(err))
    except CorpusSpecError as err:
        _print_problems("Invalid corpus spec", err.problems)
        raise typer.Exit(code=ExitCode.INPUT) from None
    return files, spec


def _print_problems(title: str, problems: Sequence[str]) -> None:
    typer.echo(f"{title} ({len(problems)} problem(s)):", err=True)
    for problem in problems:
        typer.echo(f"  - {problem}", err=True)


@corpus_app.command("verify")
def verify_corpus_command(dataset: DatasetDir = Path("datasets")) -> None:
    """Check the sealed dataset: seal, file hashes, splits, questions, counts and any audit records."""
    files, spec = _dataset(dataset)
    if problems := dataset_problems(files, spec):
        _print_problems(f"{dataset} is not intact", problems)
        raise typer.Exit(code=ExitCode.DATASET)
    typer.echo(f"{dataset} is intact and sealed ({files[SEALED].decode().strip()}).")


@corpus_app.command("seal")
def seal_corpus_command(dataset: DatasetDir = Path("datasets")) -> None:
    """Write SEALED (the manifest hash) once, only if every other check passes; never replaces a seal."""
    files, spec = _dataset(dataset)
    if problems := dataset_problems(files, spec, require_seal=False):
        _print_problems(f"{dataset} cannot be sealed", problems)
        raise typer.Exit(code=ExitCode.DATASET)
    try:
        path = write_seal(dataset, files[MANIFEST])
    except OutputConflictError as err:
        _fail(ExitCode.OUTPUT, str(err))
    typer.echo(f"sealed: {path}")


KindOption = Annotated[OverstatedReason, typer.Option("--kind", help="Trap kind to audit.")]
DEFAULT_AUDIT_DIR = Path("var/audit")  # git-ignored: sheets hold abstract text (publisher copyright)


@corpus_app.command("audit-sheet")
def audit_sheet_command(
    kind: KindOption,
    dataset: DatasetDir = Path("datasets"),
    out: Annotated[
        Path, typer.Option(help="Folder for the sheet (keep it git-ignored).")
    ] = DEFAULT_AUDIT_DIR,
    env_file: EnvFile = Path(".env"),
) -> None:
    """Export the dev audit sheet of one kind, replaying abstracts from the cache (never the network).

    Dev only until the prompt freeze (S12): a test sheet would show test abstracts before tuning ends.
    """
    files, spec = _dataset(dataset)
    settings = _settings(env_file)
    try:
        with build_replay(settings) as source:
            sheet = export_sheet(files, spec, kind, source)
        path = publish_sheet(out, AUDIT_SPLIT, kind, sheet)
    except AuditInputError as err:
        _print_problems("Cannot export the audit sheet", err.problems)
        raise typer.Exit(code=ExitCode.DATASET) from None
    except CacheMissError:
        _fail(ExitCode.CACHE_MISS, "an abstract is not in the cache; the sheet is built from the cache only")
    except CacheError as err:
        _fail(ExitCode.LOCAL_CACHE, f"cache problem: {err}")
    except OutputConflictError as err:
        _fail(ExitCode.OUTPUT, str(err))
    typer.echo(f"wrote: {path}")
    typer.echo("fill in decision (confirm/reject) and a reason for every reject, then run apply-audit")


@corpus_app.command("apply-audit")
def apply_audit_command(
    kind: KindOption,
    sheet: Annotated[Path, typer.Option("--sheet", help="The filled-in audit sheet (CSV).")],
    prompts_sha256: Annotated[
        str, typer.Option("--prompts-sha256", help="sha256 of the prompts and rule packs in force.")
    ],
    dataset: DatasetDir = Path("datasets"),
) -> None:
    """Record a filled-in dev audit sheet in the dataset, once, bound to the seal; print the precision."""
    files, spec = _dataset(dataset)
    try:
        text = sheet.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        _fail(ExitCode.INPUT, f"cannot read {sheet}: {type(err).__name__}")
    try:
        summary = apply_decisions(files, spec, kind, text, prompts_sha256=prompts_sha256)
        path = publish_audit(dataset, AUDIT_SPLIT, kind, summary.record)
    except AuditSheetError as err:
        _print_problems(f"{sheet} is not a valid audit", err.problems)
        raise typer.Exit(code=ExitCode.INPUT) from None
    except AuditInputError as err:
        _print_problems("Cannot apply the audit", err.problems)
        raise typer.Exit(code=ExitCode.DATASET) from None
    except OutputConflictError as err:
        _fail(ExitCode.OUTPUT, str(err))
    low, high = summary.interval
    typer.echo(f"wrote: {path}")
    typer.echo(
        f"precision {summary.confirmed}/{summary.reviewed} confirmed "
        f"(95% Wilson {low:.2f}-{high:.2f}); author-confirmed, single rater"
    )


challenge_app = typer.Typer(help="The dev challenge set of the verifier (ADR 0020).", no_args_is_help=True)
app.add_typer(challenge_app, name="challenge")
DEFAULT_CHALLENGE = Path("challenge/dev-v1.jsonl")
ChallengeFile = Annotated[Path, typer.Option("--challenge", help="The challenge set (JSONL).")]
CHALLENGE_DIR = "challenge"  # attempts under the var dir, by judge


def _result_path(challenge: Path) -> Path:
    return challenge.with_name(challenge.name.removesuffix(".jsonl") + ".result.json")


def _read_input(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as err:
        _fail(ExitCode.INPUT, f"cannot read {path}: {err.strerror or type(err).__name__}")


@challenge_app.command("run")
def challenge_run_command(
    challenge: ChallengeFile = DEFAULT_CHALLENGE,
    record: Annotated[
        bool, typer.Option("--record", help="Also publish <set>.result.json beside the set, once.")
    ] = False,
    dataset: DatasetDir = Path("datasets"),
    env_file: EnvFile = Path(".env"),
) -> None:
    """Judge every challenge item with the configured verifier, from its sealed dev pool. Costs tokens.

    Every attempt is kept under the var dir as challenge/<judge>.json; a read-only replay is byte-identical.
    """
    settings = _settings(env_file)
    data = _read_input(challenge)
    with _live_exit_codes(dataset):
        try:
            files = read_dataset(dataset)
            spec = load_corpus_spec(dataset / SPEC)
            judge = current_judge(settings)
            with build_challenge_ports(settings, logging_emitter()) as (ports, verifier):
                result = run_challenge(
                    ports, data, files, spec, judge_sha256=judge.sha256, verifier=verifier.deployment
                )
            out = result_bytes(result)
            attempt = publish_document(
                settings.var_dir / CHALLENGE_DIR,
                f"{judge.sha256[:16]}-{result.challenge_sha256[:8]}.json",
                out,
            )
        except ChallengeInputError as err:
            _print_problems(f"{challenge} cannot be run", err.problems)
            raise typer.Exit(code=ExitCode.INPUT) from None
        except ChallengePoolError as err:
            _fail(ExitCode.DATASET, str(err))
        except JudgeReadError as err:
            _fail(ExitCode.INPUT, str(err))
        except OutputConflictError as err:
            _fail(ExitCode.OUTPUT, str(err))
    _print_challenge(result)
    typer.echo(f"attempt: {attempt}")
    if record:
        if not result.score.passed:
            _fail(ExitCode.INPUT, "the challenge rule is not met; nothing recorded")
        try:
            path = publish_document(challenge.parent, _result_path(challenge).name, out)
        except OutputConflictError as err:
            _fail(ExitCode.OUTPUT, str(err))
        typer.echo(f"recorded: {path}")


def _print_challenge(result: ChallengeResult) -> None:
    s = result.score
    typer.echo(f"verifier: {result.verifier}; judge {result.judge_sha256[:16]}")
    typer.echo(
        f"agree {s.agree}/{s.n}; unsafe passes {s.unsafe_passes}; failed or absent evidence "
        f"{s.failures_or_absent}; near {s.near}; supported but negated {s.negated_supported}"
    )
    for label, counts in s.table.items():
        typer.echo(f"  {label}: " + (", ".join(f"{d}={n}" for d, n in counts.items()) or "none"))
    typer.echo(
        f"challenge rule: {'met' if s.passed else 'NOT met'} (author-confirmed, single rater; not accuracy)"
    )


freeze_app = typer.Typer(help="The prompt freeze record (ADR 0020).", no_args_is_help=True)
app.add_typer(freeze_app, name="freeze")


@freeze_app.command("write")
def freeze_write_command(
    name: Annotated[str, typer.Option("--name", help="Freeze name, e.g. v1.")] = "v1",
    challenge: ChallengeFile = DEFAULT_CHALLENGE,
    dataset: DatasetDir = Path("datasets"),
    out: Annotated[Path, typer.Option(help="Folder for freeze records.")] = Path(FREEZE_DIR),
    env_file: EnvFile = Path(".env"),
) -> None:
    """Write freeze/<name>.json once, only if the committed challenge result attests this judge."""
    settings = _settings(env_file)
    files, _ = _dataset(dataset)
    data = _read_input(challenge)
    result = _read_input(_result_path(challenge))
    try:
        judge = current_judge(settings)
    except JudgeReadError as err:
        _fail(ExitCode.INPUT, str(err))
    verifier = str(judge.verifier["deployment"])
    if problems := attestation_problems(data, result, files, judge_sha256=judge.sha256, verifier=verifier):
        _print_problems("Cannot freeze", problems)
        raise typer.Exit(code=ExitCode.INPUT)
    record = freeze_record(name, judge, result)
    try:
        path = publish_document(out, f"{name}.json", pretty_json_bytes(record.model_dump(mode="json")))
    except OutputConflictError as err:
        _fail(ExitCode.OUTPUT, str(err))
    typer.echo(f"wrote: {path}")
    typer.echo(f"file sha256 (pin it in app/freeze.py FROZEN): {_sha256(path.read_bytes())}")
    typer.echo(f"freeze_sha256: {record.freeze_sha256}")


def _fail(code: ExitCode, message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=code)


def _print_paper(rank: int, paper: Paper) -> None:
    flag = " [RETRACTED]" if paper.retracted else ""
    year = paper.year if paper.year is not None else "n.d."
    typer.echo(f"\n{rank}. {paper.source_id} ({year}){flag} {paper.title}")
    typer.echo(f"   {paper.abstract}")
