from pathlib import Path

import pytest
from typer.testing import CliRunner

from bio_claim_check import __version__
from bio_claim_check.app.cli import app

pytestmark = pytest.mark.unit
runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"bio-claim-check {__version__}"


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "Usage" in result.output


def test_config_redacts_secrets(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "BCC_CONTACT_EMAIL=someone@example.org\n"
        "BCC_FOUNDRY__BASE_URL=https://example-resource.services.ai.azure.com\n"
        "BCC_FOUNDRY__API_KEY=super-secret-value\n"
    )
    result = runner.invoke(app, ["config", "--env-file", str(env)])
    assert result.exit_code == 0, result.output
    assert "super-secret-value" not in result.output
    assert "providers: foundry" in result.output


def test_config_reports_problems_without_echoing_input(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("BCC_CONTACT_EMAIL=someone@example.org\nBCC_FOUNDRY__API_KEY=super-secret-value\n")
    result = runner.invoke(app, ["config", "--env-file", str(env)])
    assert result.exit_code == 2
    assert "foundry.base_url" in result.output
    assert "super-secret-value" not in result.output
