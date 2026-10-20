from pathlib import Path

import pytest
from pydantic import ValidationError

from bio_claim_check.app.settings import Settings, load_settings

pytestmark = pytest.mark.unit

FOUNDRY = {"base_url": "https://example-resource.services.ai.azure.com", "api_key": "not-a-real-key"}


def make(**overrides: object) -> Settings:
    values: dict[str, object] = {"contact_email": "someone@example.org", "foundry": FOUNDRY}
    values.update(overrides)
    return Settings.model_validate(values)


def test_defaults_bind_three_model_roles() -> None:
    s = make()
    assert (s.answer_model, s.verifier_model, s.trap_model) == (
        "gpt-6.1-sol",
        "claude-opus-4-8",
        "Kimi-K2.6-1",
    )
    assert s.cache_mode == "read-write"
    assert s.var_dir == Path("var")


def test_live_mode_without_any_provider_fails_fast() -> None:
    with pytest.raises(ValidationError, match="at least one LLM provider"):
        make(foundry=None)


def test_read_only_replay_needs_no_provider() -> None:
    assert make(foundry=None, cache_mode="read-only").configured_providers == ()


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
