"""[TEST SUPPORT] Repository paths, resolved from this file so tests never depend on the CWD."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
PACKAGE = SRC / "bio_claim_check"
FEATURES = PACKAGE / "features"
DOCS = ROOT / "docs"
ADR_DIR = DOCS / "adr"
PYPROJECT = ROOT / "pyproject.toml"
VENV_BIN = Path(sys.executable).parent  # the environment running pytest, wherever uv put it
