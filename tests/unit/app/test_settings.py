from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.support.settings import make_settings

from bio_claim_check.app.settings import Settings, UiSettings, load_settings, load_ui_settings
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
        "gpt-6.1-sol",
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


def test_the_ui_starts_without_a_contact_email_or_any_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("BCC_CONTACT_EMAIL", "BCC_VAR_DIR", "BCC_CACHE_MODE"):
        monkeypatch.delenv(key, raising=False)
    ui = load_ui_settings(None)
    assert ui.var_dir == Path("var")
    assert ui.cache_mode is CacheMode.READ_WRITE
    assert set(UiSettings.model_fields) == {"var_dir", "cache_mode"}


def test_the_ui_reads_its_keys_from_the_same_env_file_and_ignores_the_rest(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "BCC_CONTACT_EMAIL=someone@example.org\nBCC_VAR_DIR=elsewhere\nBCC_CACHE_MODE=read-only\n"
        "BCC_ANTHROPIC__API_KEY=not-a-real-key\nBCC_MAX_LIVE_LLM_CALLS=3\n"
    )
    ui = load_ui_settings(env)
    assert ui.var_dir == Path("elsewhere")
    assert ui.cache_mode is CacheMode.READ_ONLY
    assert load_settings(env).var_dir == ui.var_dir
