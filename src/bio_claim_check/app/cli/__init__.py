"""[RING:app/cli] Command-line driving adapter — the primary interface.

The CLI parses arguments, calls the composition root and renders results. It holds no business logic:
anything worth testing lives in ``features`` or ``app.usecases`` and is called from here. It reaches
infrastructure only through ``app.container`` (contract ``driving-adapters-use-the-container``).
"""

import re
from datetime import date
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from bio_claim_check import __version__
from bio_claim_check.app.container import (
    OutputConflictError,
    build_fake_run_ports,
    build_retrieval,
    default_rulepack,
    load_corpus_spec,
    load_rulepack,
    publish_corpus,
    publish_report,
)
from bio_claim_check.app.settings import Settings, load_settings
from bio_claim_check.app.usecases.build_corpus import PoolConflictError, build_corpus
from bio_claim_check.app.usecases.run import run_question
from bio_claim_check.engine.cache.policy import CacheError, CacheMissError
from bio_claim_check.features.contracts.corpus import CorpusManifest, CorpusSpecError
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.rulepack import RulePack, RulePackError
from bio_claim_check.features.retrieval.errors import RetrievalError

DEFAULT_K = 4
DEFAULT_RETRIEVE_K = 10
EXIT_INPUT = 2  # bad arguments or configuration
EXIT_CACHE_MISS = 3  # read-only cache mode and the request is not cached
EXIT_UPSTREAM = 4  # the literature database failed
EXIT_LOCAL_CACHE = 5  # the cache file cannot be opened, read or written
EXIT_OUTPUT = 6  # an output file exists with different bytes or cannot be written (nothing is overwritten)

_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")  # date.fromisoformat also takes 20250115 and 2025-W03-3
DEFAULT_RUNS_DIR = Path("var/runs")  # relative to the working directory; --fake never reads settings

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


def _settings(env_file: Path) -> Settings:
    """Validated settings, or every problem on stderr (never the offending values) and exit 2."""
    try:
        return load_settings(env_file if env_file.exists() else None)
    except ValidationError as err:
        typer.echo(f"Invalid configuration ({err.error_count()} problem(s)):", err=True)
        for problem in err.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in problem["loc"]) or "settings"
            typer.echo(f"  - {location}: {problem['msg']}", err=True)
        raise typer.Exit(code=EXIT_INPUT) from None
    except (OSError, UnicodeDecodeError) as err:
        typer.echo(f"Cannot read {env_file}: {type(err).__name__}", err=True)
        raise typer.Exit(code=EXIT_INPUT) from None


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
        raise typer.Exit(code=2) from None
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
    question: Annotated[str, typer.Argument(help="The research question to answer and check.")],
    fake: Annotated[
        bool, typer.Option("--fake", help="Fictional papers, scripted answer and verdicts (offline demo).")
    ] = False,
    mode: Annotated[AnswerMode, typer.Option(help="How the answering agent behaves.")] = AnswerMode.STRICT,
    k: Annotated[int, typer.Option("--k", min=1, help="Number of papers to retrieve.")] = DEFAULT_K,
    out: Annotated[Path, typer.Option(help="Folder that receives <run_id>/report.json.")] = DEFAULT_RUNS_DIR,
) -> None:
    """Answer a question, check every claim against the paper it cites, and write the report."""
    if not fake:
        typer.echo("Live runs arrive in S12; use --fake for the offline demo.", err=True)
        raise typer.Exit(code=2)
    if not question.strip():
        typer.echo("The question must not be blank.", err=True)
        raise typer.Exit(code=2)
    report = run_question(build_fake_run_ports(), question, mode, k=k)
    typer.echo(report.notice)
    path = publish_report(out, report)
    typer.echo(f"report: {path}")
    for name, counts in (("pairs", report.pair_counts), ("claims", report.claim_counts)):
        typer.echo(f"{name}: " + ", ".join(f"{d.value}={n}" for d, n in counts.items()))
    for note in report.notes:
        typer.echo(f"note: {note}")


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
        _fail(EXIT_INPUT, str(err))
    except CacheMissError:
        _fail(EXIT_CACHE_MISS, "not in the cache and BCC_CACHE_MODE=read-only; run once with read-write")
    except RetrievalError as err:
        _fail(EXIT_UPSTREAM, f"retrieval failed: {err}")
    except CacheError as err:
        _fail(EXIT_LOCAL_CACHE, f"cache problem: {err}")
    typer.echo(f"{len(papers)} citable paper(s) from Europe PMC (MEDLINE/PubMed-indexed abstracts)")
    typer.echo("retraction status is as of the first fetch (cached snapshot)")
    for rank, paper in enumerate(papers, start=1):
        _print_paper(rank, paper)


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
        _fail(EXIT_INPUT, f"--declared-fetched-on must be YYYY-MM-DD, got {declared_fetched_on!r}")
    try:
        corpus_spec = load_corpus_spec(spec)
    except CorpusSpecError as err:
        typer.echo(f"Invalid corpus spec ({len(err.problems)} problem(s)):", err=True)
        for problem in err.problems:
            typer.echo(f"  - {problem}", err=True)
        raise typer.Exit(code=EXIT_INPUT) from None
    settings = _settings(env_file)
    try:
        with build_retrieval(settings) as source:
            files = build_corpus(
                corpus_spec, source, declared_fetched_on=fetched_on, tool_version=__version__
            )
        paths = publish_corpus(out, files)
    except ValueError as err:
        _fail(EXIT_INPUT, str(err))
    except CacheMissError:
        _fail(EXIT_CACHE_MISS, "not in the cache and BCC_CACHE_MODE=read-only; run once with read-write")
    except (RetrievalError, PoolConflictError) as err:
        _fail(EXIT_UPSTREAM, f"retrieval failed: {err}")
    except CacheError as err:
        _fail(EXIT_LOCAL_CACHE, f"cache problem: {err}")
    except OutputConflictError as err:
        _fail(EXIT_OUTPUT, str(err))
    manifest = CorpusManifest.model_validate_json(files.manifest)
    typer.echo(manifest.notice)
    for path in paths:
        typer.echo(f"wrote: {path}")
    typer.echo("candidates (domain, split, kind: n):")
    for c in manifest.candidate_counts:
        typer.echo(f"  {c.domain} {c.split.value} {c.kind.value}: {c.n}")


def _fail(code: int, message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=code)


def _print_paper(rank: int, paper: Paper) -> None:
    flag = " [RETRACTED]" if paper.retracted else ""
    year = paper.year if paper.year is not None else "n.d."
    typer.echo(f"\n{rank}. {paper.source_id} ({year}){flag} {paper.title}")
    typer.echo(f"   {paper.abstract}")
