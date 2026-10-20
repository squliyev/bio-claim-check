"""Global test fixtures. Tests never read the developer's real ``.env`` or ``BCC_*`` environment."""

import os

import pytest

from bio_claim_check.app.settings import ENV_PREFIX


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    for key in list(os.environ):  # tests/** may read the env (TID251 is relaxed there)
        if key.startswith(ENV_PREFIX):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))  # a stray ./.env can never leak into a test
