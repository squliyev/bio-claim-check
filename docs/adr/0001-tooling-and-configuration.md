# ADR 0001 — Tooling and configuration

- **Status:** Accepted
- **Date:** 2026-10-20
- **Supersedes / Extends:** —
- **Related:** 0002
- **Enforced by:** `uv sync --frozen` in CI · pyright strict · ruff `TID251` (`os.environ`, `os.getenv`, `os.putenv`) · `tests/unit/app/test_settings.py` · `tests/arch/test_ruff_bans.py::test_env_access_banned_outside_settings` · gitleaks (pre-commit and CI)

## Context

This is research software whose results other people must be able to re-run and trust. Three things
erode that trust quietly:

- Environments that differ between machines.
- Type errors found only at run time.
- Configuration read ad hoc from the environment, so a typo surfaces as a `KeyError` deep inside a
  provider call.

Secrets and private endpoints must also never reach git.

## Decision

- **Environment:** `uv` with a committed, hash-pinned `uv.lock`. Every install in CI and in Docker uses
  `--frozen`. Python is pinned to 3.13 (`.python-version`), and minor upgrades are a deliberate decision.
- **Types:** pyright in **strict** mode over `src/` and `tests/`.
- **Lint:** ruff, including no blind `except` (`BLE`), no `print` (`T20`), bandit (`S`) and banned APIs
  (`TID251`). Relative imports are banned.
- **Configuration:**
  - `bio_claim_check.app.settings` is the **only** module that reads the process environment.
  - It validates once at startup (pydantic-settings, `BCC_` prefix, `extra="forbid"`, frozen) and hands
    a typed `Settings` object to everything else.
  - Secrets are `SecretStr` and are redacted in every output.
- **Secrets hygiene:**
  - `.env*` is git-ignored except `.env.example`, which contains placeholders only.
  - gitleaks runs in pre-commit and on full history in CI, with a project rule that blocks real Azure AI
    endpoints.
- **One gate:** `make verify` runs the same lint, type and test commands locally and in CI. All CI
  actions are pinned by commit SHA and updated by Dependabot.

## Consequences

- **Positive:**
  - A reviewer can reproduce the exact environment.
  - Configuration errors fail at startup with a precise message.
  - Agent-written code is held to the same bar as hand-written code.
- **Negative / costs:**
  - Strict typing slows quick experiments; experiments belong in notebooks outside `src/`.
- **Follow-ups:**
  - `pip-audit` in S21.
  - S06 note: the S01 settings check "live modes need at least one LLM provider" was removed. Retrieval
    needs only `contact_email`, and "any provider" was the wrong test anyway. S08 adds a per-role check
    when the models are built, before any network call. Validation is not loosened, only moved to where
    the requirement is known.
