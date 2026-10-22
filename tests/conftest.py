"""Global test fixtures. Tests never read the developer's real ``.env`` or ``BCC_*`` environment.

Offline tests (everything not marked ``live``) cannot open internet sockets, in-process or in a Python
subprocess (I31, ``tests/support/netblock``). ``live`` tests keep only ``BCC_CONTACT_EMAIL`` from the
environment, because Europe PMC asks for a contact address.

``--update-golden`` rewrites golden files and fails the test on purpose; it is refused when ``CI`` is set.

Hypothesis profiles: ``dev`` (default) and ``ci`` (derandomized, more examples), chosen with
``HYPOTHESIS_PROFILE``. An unknown name raises, so a typo cannot silently fall back to ``dev``.
"""

import logging
import os
from collections.abc import Iterable, Iterator, Mapping

import pytest
from hypothesis import settings

from bio_claim_check.app.settings import ENV_PREFIX
from tests.support.netblock import NETBLOCK_DIR
from tests.support.netblock.sitecustomize import PATCHES

LIVE_KEEPS = frozenset({f"{ENV_PREFIX}CONTACT_EMAIL"})

settings.register_profile("dev", max_examples=200)
settings.register_profile("ci", max_examples=1000, derandomize=True, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        help="Rewrite golden files, then fail on purpose so a regenerated file is never a silent pass.",
    )


@pytest.fixture
def update_golden(request: pytest.FixtureRequest) -> bool:
    if not request.config.getoption("--update-golden"):
        return False
    if os.environ.get("CI"):
        pytest.fail("--update-golden is refused in CI; regenerate locally and review the diff")
    return True


def is_live(keywords: Mapping[str, object]) -> bool:
    """True only for the `live` marker (incl. module `pytestmark`), which appears in keywords as a `Mark`.

    Node names are keywords too (a `tests/live/` folder gives `"live": True`), so membership is not enough.
    """
    return isinstance(keywords.get("live"), pytest.Mark)


def scrubbed(names: Iterable[str], *, live: bool) -> list[str]:
    """The `BCC_` variables a test must not see; `live` tests keep only the contact address."""
    keep = LIVE_KEEPS if live else frozenset[str]()
    return [name for name in names if name.startswith(ENV_PREFIX) and name not in keep]


@pytest.fixture(autouse=True)
def _isolate_env(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    for key in scrubbed(list(os.environ), live=is_live(request.keywords)):  # TID251 is relaxed in tests/
        monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))  # a stray ./.env can never leak into a test


@pytest.fixture(autouse=True)
def _restore_package_logger() -> Iterator[None]:
    """`configure_logging` (called by every CLI command that loads settings) changes the package logger
    process-wide; undo it so a later test's `caplog` still sees records."""
    logger = logging.getLogger("bio_claim_check")
    saved = (list(logger.handlers), logger.level, logger.propagate)
    yield
    logger.handlers[:] = saved[0]
    logger.setLevel(saved[1])
    logger.propagate = saved[2]


@pytest.fixture(autouse=True)
def _block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if is_live(request.keywords):
        return
    for target, name, replacement in PATCHES:
        monkeypatch.setattr(target, name, replacement)
    inherited = os.environ.get("PYTHONPATH")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, [str(NETBLOCK_DIR), inherited])))
