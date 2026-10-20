"""[RING:app/cli] Command-line driving adapter — the primary interface.

The CLI parses arguments, calls the composition root and renders results. It holds no business logic:
anything worth testing lives in ``features`` or ``app.usecases`` and is called from here.
"""

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from bio_claim_check import __version__
from bio_claim_check.app.container import build_fake_container
from bio_claim_check.app.settings import load_settings
from bio_claim_check.app.usecases.run import run_question
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.contracts.rulepack import RulePack
from bio_claim_check.infrastructure.rulepack_yaml import RulePackError, load_default_rulepack, load_rulepack
from bio_claim_check.infrastructure.run_store import write_report

DEFAULT_K = 4
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


@app.command("config")
def show_config(
    env_file: Annotated[
        Path, typer.Option(help="Dotenv file to read in addition to the environment.")
    ] = Path(".env"),
) -> None:
    """Validate configuration and print it with secrets redacted."""
    try:
        settings = load_settings(env_file if env_file.exists() else None)
    except ValidationError as err:
        typer.echo(f"Invalid configuration ({err.error_count()} problem(s)):", err=True)
        for problem in err.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in problem["loc"]) or "settings"
            typer.echo(f"  - {location}: {problem['msg']}", err=True)
        raise typer.Exit(code=2) from None
    typer.echo(settings.model_dump_json(indent=2))
    typer.echo(f"providers: {', '.join(settings.configured_providers) or 'none (replay only)'}")


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
        pack = load_default_rulepack() if path is None else load_rulepack(path)
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
    report = run_question(build_fake_container(), question, mode, k=k)
    typer.echo(report.notice)
    path = write_report(out, report)
    typer.echo(f"report: {path}")
    for name, counts in (("pairs", report.pair_counts), ("claims", report.claim_counts)):
        typer.echo(f"{name}: " + ", ".join(f"{d.value}={n}" for d, n in counts.items()))
    for note in report.notes:
        typer.echo(f"note: {note}")
