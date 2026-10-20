"""The committed JSON Schemas equal what the contracts generate (`make schemas` refreshes them)."""

import importlib.util
from types import ModuleType

import pytest

from tests.support.paths import ROOT

pytestmark = pytest.mark.arch


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_schemas", ROOT / "scripts" / "gen_schemas.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_schemas_are_fresh() -> None:
    gen = _generator()
    committed = {p.name for p in (ROOT / "schemas").glob("*.json")}
    assert committed == set(gen.SCHEMAS), "schemas/ holds exactly the generated files"
    for name, build in gen.SCHEMAS.items():
        text = (ROOT / "schemas" / name).read_text(encoding="utf-8")
        assert text == gen.render(build), f"schemas/{name} is stale: run `make schemas`"
