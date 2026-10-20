"""Global test fixtures. Tests never read the developer's real ``.env`` or ``BCC_*`` environment.

Hypothesis profiles: ``dev`` (default) and ``ci`` (derandomized, more examples), chosen with
``HYPOTHESIS_PROFILE``. An unknown name raises, so a typo cannot silently fall back to ``dev``.
"""

import os

import pytest
from hypothesis import settings

from bio_claim_check.app.settings import ENV_PREFIX

settings.register_profile("dev", max_examples=200)
settings.register_profile("ci", max_examples=1000, derandomize=True, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    for key in list(os.environ):  # tests/** may read the env (TID251 is relaxed there)
        if key.startswith(ENV_PREFIX):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))  # a stray ./.env can never leak into a test
