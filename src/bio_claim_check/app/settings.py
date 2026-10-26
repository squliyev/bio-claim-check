"""[RING:app] Validated configuration — the single place the process environment is read.

Why: configuration errors should fail once, at startup, with a precise message — not as a ``KeyError``
deep inside a provider call. Every other module receives a typed ``Settings`` object; reading
``os.environ`` anywhere else is banned by ruff ``TID251`` (ADR 0001).

Secrets are ``SecretStr`` so they never appear in ``repr``, logs or the ``config`` command output.
Real values live only in the git-ignored ``.env`` file; ``.env.example`` documents every key.
"""

from pathlib import Path
from typing import Final, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, EmailStr, PositiveInt, SecretStr
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
    """The single writable root: cache, runs, event traces, the run ledger, annotations."""

    cache_mode: CacheMode = CacheMode.READ_WRITE
    """``read-only`` replays from cache and fails closed on a miss (CI and offline demos). ADR 0009."""

    max_live_llm_calls: PositiveInt = 40
    """The most live LLM calls one command may make; cache hits are free; refused before the call."""

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
    trap_model: str = "gpt-6.1-sol"
    """S13 (ADR 0022): the answerer's deployment; not the verifier's family. Kimi is deferred (A10)."""

    # No global "a provider must be configured" check: retrieval (S06) needs none. The LLM roles check
    # their own provider when they are built (S08), so the error names the role that needs it.

    @property
    def configured_providers(self) -> tuple[str, ...]:
        candidates = {"foundry": self.foundry, "anthropic": self.anthropic, "ollama": self.ollama}
        return tuple(name for name, cfg in candidates.items() if cfg is not None)


CHECKPOINT_RESULT: Final = Path("traps/results/v2-dev-v1.json")
"""The committed proof-checkpoint result (ADR 0024) the UI's About page shows in full, relative to the
working directory (the repository, or the container's workdir). A constant, not a setting: `Settings`
forbids unknown `.env` keys, and there is one committed result per freeze."""


SEALED_DATASET: Final = Path("datasets")
"""The sealed corpus whose test-split ids live `check` and `run` refuse (I84), relative to the working
directory (the repository, or the container's workdir). A constant for the same reason as
`CHECKPOINT_RESULT`; `run --dev` and the dataset commands still take `--dataset`."""


class UiSettings(BaseSettings):
    """What the UI needs to start and show recorded runs: no secrets and no contact email (S17a, R3).

    The full `Settings` is loaded only when a live action starts, so an offline demo without a `.env`
    still shows recorded runs, fictional runs and the About page. Other `BCC_` keys are ignored here;
    `Settings` validates them when it is loaded. Both read the same `.env`, so they agree on `var_dir`.
    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        frozen=True,
    )

    var_dir: Path = Path("var")
    """The same root as `Settings.var_dir`: recorded runs are read from it, fictional runs written to it."""

    cache_mode: CacheMode = CacheMode.READ_WRITE
    """``read-only`` disables live actions in the UI, so a click can never reach a provider."""


def load_ui_settings(env_file: Path | None = Path(".env")) -> UiSettings:
    """Load the UI's settings from the environment and, if present, ``env_file``."""
    return UiSettings(_env_file=env_file)  # pyright: ignore[reportCallIssue] - as in `load_settings`


def load_settings(env_file: Path | None = Path(".env")) -> Settings:
    """Load settings from the environment and, if present, ``env_file``. Pass ``None`` to skip the file."""
    # `_env_file` is a pydantic-settings init kwarg that its typed signature omits
    return Settings(_env_file=env_file)  # pyright: ignore[reportCallIssue]
