"""`bio-claim-check rulepack validate`: summary on success, one located line per problem on failure."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from bio_claim_check.app.cli import app

pytestmark = pytest.mark.unit
runner = CliRunner()


def test_the_default_pack_is_valid() -> None:
    result = runner.invoke(app, ["rulepack", "validate"])
    assert result.exit_code == 0, result.output
    assert "rules: 9" in result.stdout
    assert "(18 author-written, 0 reviewed)" in result.stdout


def test_a_broken_pack_exits_2_with_locations(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("schema_version: true\nversion: '1.0'\nversion: '1.0.0'\n", encoding="utf-8")
    result = runner.invoke(app, ["rulepack", "validate", str(path)])
    assert result.exit_code == 2
    assert f"{path}:3: duplicate key 'version'" in result.stderr
    assert result.stdout == ""


def test_model_problems_are_listed_one_per_line(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("schema_version: true\nversion: '1.0'\n", encoding="utf-8")
    result = runner.invoke(app, ["rulepack", "validate", str(path)])
    assert result.exit_code == 2
    assert "(4 problem(s))" in result.stderr
    assert f"{path}: schema_version: Value error, must be the integer 1" in result.stderr
