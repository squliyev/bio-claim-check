"""[RING:app] Validated configuration — the single place the process environment is read.

Why: configuration errors should fail once, at startup, with a precise message — not as a ``KeyError``
deep inside a provider call. Every other module receives a typed ``Settings`` object; reading
``os.environ`` anywhere else is banned by ruff ``TID251`` (ADR 0001).

Secrets are ``SecretStr`` so they never appear in ``repr``, logs or the ``config`` command output.
Real values live only in the git-ignored ``.env`` file; ``.env.example`` documents every key.
"""

from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, EmailStr, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from bio_claim_check.engine.cache.policy import CacheMode

type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
type LogFormat = Literal["json", "text"]

ENV_PREFIX = "BCC_"


class FoundrySettings(BaseModel):
    """Azure AI Foundry resource. ``base_url`` is the resource endpoint, never committed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: AnyHttpUrl
    api_key: SecretStr


class AnthropicSettings(BaseModel):
    """Direct Anthropic API access."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key: SecretStr


class OllamaSettings(BaseModel):
    """Local Ollama server (open-weight models, no key)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:11434")


class Settings(BaseSettings):
    """Process configuration. Construct with :func:`load_settings`; never instantiate ad hoc in features."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="forbid",
        frozen=True,
    )

    contact_email: EmailStr
    """Sent in the User-Agent to Europe PMC, as their usage etiquette asks."""

    var_dir: Path = Path("var")
    """The single writable root: cache, ledger, runs, annotations."""

    cache_mode: CacheMode = CacheMode.READ_WRITE
    """``read-only`` replays from cache and fails closed on a miss (CI and offline demos). ADR 0009."""

    log_level: LogLevel = "WARNING"
    """Applied by `app.logging_setup` (S08b). WARNING shows only retries and problems; INFO adds progress.
    Before S08b this setting was read but never applied, so a `.env` with INFO now prints progress lines."""

    log_format: LogFormat = "json"
    """``json`` (one object per line, for machines) or ``text`` (for a terminal). Logs go to stderr only."""

    foundry: FoundrySettings | None = None
    anthropic: AnthropicSettings | None = None
    ollama: OllamaSettings | None = None

    answer_model: str = "gpt-6.1-sol"
    verifier_model: str = "claude-opus-4-8"
    trap_model: str = "Kimi-K2.6-1"

    # No global "a provider must be configured" check: retrieval (S06) needs none. The LLM roles check
    # their own provider when they are built (S08), so the error names the role that needs it.

    @property
    def configured_providers(self) -> tuple[str, ...]:
        candidates = {"foundry": self.foundry, "anthropic": self.anthropic, "ollama": self.ollama}
        return tuple(name for name, cfg in candidates.items() if cfg is not None)


def load_settings(env_file: Path | None = Path(".env")) -> Settings:
    """Load settings from the environment and, if present, ``env_file``. Pass ``None`` to skip the file."""
    # `_env_file` is a pydantic-settings init kwarg that its typed signature omits
    return Settings(_env_file=env_file)  # pyright: ignore[reportCallIssue]
