from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.support.settings import make_settings

from bio_claim_check.app.settings import Settings, load_settings
from bio_claim_check.engine.cache.policy import CacheMode

pytestmark = pytest.mark.unit

FOUNDRY = {"base_url": "https://example-resource.services.ai.azure.com", "api_key": "not-a-real-key"}


def make(**overrides: object) -> Settings:
    return make_settings(**{"foundry": FOUNDRY, **overrides})


def test_defaults_bind_three_model_roles() -> None:
    s = make()
    assert (s.answer_model, s.verifier_model, s.trap_model) == (
        "gpt-6.1-sol",
        "claude-opus-4-8",
        "Kimi-K2.6-1",
    )
    assert s.cache_mode == "read-write"
    assert s.var_dir == Path("var")


def test_retrieval_needs_no_provider() -> None:
    assert make(foundry=None).configured_providers == ()


def test_cache_mode_is_the_engine_enum() -> None:
    assert make(cache_mode="read-only").cache_mode is CacheMode.READ_ONLY
    with pytest.raises(ValidationError, match="cache_mode"):
        make(cache_mode="readonly")


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        make(verifer_model="typo")


def test_secrets_never_render() -> None:
    s = make()
    assert "not-a-real-key" not in repr(s)
    assert "not-a-real-key" not in s.model_dump_json()


def test_invalid_email_rejected() -> None:
    with pytest.raises(ValidationError, match="contact_email"):
        make(contact_email="not-an-email")


def test_env_and_nested_delimiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BCC_CONTACT_EMAIL", "someone@example.org")
    monkeypatch.setenv("BCC_OLLAMA__BASE_URL", "http://ollama:11434")
    s = load_settings(env_file=None)
    assert s.ollama is not None
    assert str(s.ollama.base_url) == "http://ollama:11434/"


def test_dotenv_file_is_read(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("BCC_CONTACT_EMAIL=someone@example.org\nBCC_CACHE_MODE=read-only\n")
    assert load_settings(env_file=env).cache_mode == "read-only"
