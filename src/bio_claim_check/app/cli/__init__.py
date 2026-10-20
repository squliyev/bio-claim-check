"""[RING:app/cli] Command-line driving adapter — the primary interface.

The CLI parses arguments, calls the composition root and renders results. It holds no business logic:
anything worth testing lives in ``features`` or ``app.usecases`` and is called from here.
"""

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from bio_claim_check import __version__
from bio_claim_check.app.settings import load_settings

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
