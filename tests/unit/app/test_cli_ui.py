"""`ui`: the launcher replaces itself with `streamlit run page.py`, headless, and never imports streamlit."""

import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bio_claim_check.app import cli

pytestmark = pytest.mark.unit


def test_ui_execs_streamlit_on_the_page_with_the_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    def execv(path: str, argv: list[str]) -> None:
        calls.append((path, list(argv)))

    monkeypatch.setattr(cli.os, "execv", execv)
    argv_in = ["ui", "--port", "8600", "--address", "127.0.0.2", "--env-file", "x.env"]
    result = CliRunner().invoke(cli.app, argv_in)
    assert result.exit_code == 0, result.output
    ((path, argv),) = calls
    assert path == sys.executable
    assert argv == cli.ui_command(8600, "127.0.0.2", Path("x.env"))
    assert argv[1:5] == ["-m", "streamlit", "run", str(cli.UI_PAGE)]
    assert argv[argv.index("--server.headless") + 1] == "true"
    assert argv[argv.index("--browser.gatherUsageStats") + 1] == "false"
    assert argv[argv.index("--browser.serverAddress") + 1] == "localhost"  # no public-IP lookup
    assert argv[-3:] == ["--", "--env-file", "x.env"]
    assert cli.UI_PAGE.is_file()


def test_the_cli_does_not_import_streamlit() -> None:
    code = "import sys, bio_claim_check.app.cli; assert 'streamlit' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603 - fixed argv, this interpreter
