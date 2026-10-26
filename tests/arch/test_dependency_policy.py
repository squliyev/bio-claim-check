"""Every direct runtime dependency is classified, and the classification matches the import contracts.

Mirrors dependency-cruiser's "every dependency is accounted for": adding an SDK to ``[project]`` without
deciding where it may be imported fails here. Scope is DIRECT requirements only; transitive packages
(e.g. email-validator via ``pydantic[email]``) are not imported by our code and are not classified.
"""

import subprocess
import tomllib
from typing import Literal, cast

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from tests.support.fixture_pkg import ForbiddenContract, load_contracts
from tests.support.paths import DOCS, PYPROJECT, ROOT, VENV_BIN

pytestmark = pytest.mark.arch

# core: any module may import it. driver: only infrastructure, app and backend modules (ADR 0007).
type Policy = Literal["core", "driver"]

# distribution -> (import root, where it may be imported)
DIRECT_DEPENDENCIES: dict[str, tuple[str, Policy]] = {
    "anthropic": ("anthropic", "driver"),
    "httpx": ("httpx", "driver"),
    "httpx2": ("httpx2", "driver"),
    "openai": ("openai", "driver"),
    "pydantic": ("pydantic", "core"),
    "pydantic-settings": ("pydantic_settings", "driver"),
    "pyyaml": ("yaml", "driver"),
    "rapidfuzz": ("rapidfuzz", "core"),
    "streamlit": ("streamlit", "driver"),
    "typer": ("typer", "driver"),
}


def _direct_requirements() -> list[str]:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    return [str(canonicalize_name(Requirement(r).name)) for r in cast(list[str], project["dependencies"])]


def _driver_free_forbidden() -> set[str]:
    io = next(c for c in load_contracts(PYPROJECT).contracts if c.id == "pure-modules-import-no-drivers")
    assert isinstance(io, ForbiddenContract)
    return set(io.forbidden_modules)


def test_every_direct_dependency_is_classified_exactly_once() -> None:
    names = _direct_requirements()
    assert len(names) == len(set(names)), f"duplicate requirement: {names}"
    assert set(names) == set(DIRECT_DEPENDENCIES)


@pytest.mark.parametrize(("dist", "policy"), [(d, p) for d, (_, p) in DIRECT_DEPENDENCIES.items()])
def test_policy_matches_the_driver_contract(dist: str, policy: Policy) -> None:
    import_root = DIRECT_DEPENDENCIES[dist][0]
    assert (import_root in _driver_free_forbidden()) is (policy == "driver"), dist


def test_extras_do_not_change_the_distribution() -> None:
    assert str(canonicalize_name(Requirement("pydantic[email]>=2.9").name)) == "pydantic"
    assert str(canonicalize_name(Requirement("Pydantic_Settings>=2").name)) == "pydantic-settings"


# ---------------------------------------------------------------- generated dependency graph

GRAPHS = {"rings.dot": "bio_claim_check", "features.dot": "bio_claim_check.features"}


@pytest.mark.parametrize(("name", "module"), GRAPHS.items())
def test_committed_dependency_graph_is_fresh(name: str, module: str) -> None:
    """DOT only (deterministic, no graphviz needed in CI). Regenerate with `make graph`."""
    done = subprocess.run(  # noqa: S603 — fixed absolute executable, no shell
        [str(VENV_BIN / "import-linter"), "drawgraph", module, "--show-cycle-breakers"],
        cwd=ROOT,
        env={"PATH": str(VENV_BIN), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    committed = (DOCS / "architecture" / name).read_text(encoding="utf-8")
    assert done.stdout == committed, f"docs/architecture/{name} is stale: run `make graph`"
