# ADR 0013 — Canonical JSON, typed errors with stable codes, and redacted logging

- **Status:** Accepted
- **Date:** 2026-10-22
- **Supersedes / Extends:** Extends 0001 (configuration is read in one place) and 0012 (usage and cost)
- **Related:** 0009, 0011
- **Enforced by:** ruff `TID251` (`json.dumps`/`json.dump` banned outside `common/canonical_json.py`) · `tests/arch/test_ruff_bans.py::test_json_serialisation_banned_outside_canonical_json` · `tests/unit/common/test_canonical_json.py` · `tests/arch/test_error_codes.py` · `tests/unit/app/test_logging_setup.py` · `tests/unit/engine/test_llm_usage.py`

## Context

Before this decision the package had five inline copies of `json.dumps(...)` with slightly different
arguments, one of which did not refuse NaN. Errors subclassed stdlib exceptions directly, so nothing tied a
failure to a stable, documented name. The CLI used bare integers as exit codes in three places. Nothing was
logged in a structured way, and nothing stopped a secret from reaching a log line. `Usage.reasoning_tokens`
defaulted to `0`, which made "the provider did not report it" look like "the model used none".

S09 adds provider adapters on top of all four, so they were fixed first, without changing a single output
byte. Before the refactor, a manifest of every dataset file and golden plus a probe of every hash and
serialised artifact was recorded. After it, both were identical, and the dataset seal still verified.

## Decision

1. **One canonical JSON module** (`common/canonical_json.py`) with two frozen variants:
   `compact_json` (hashes and cache keys) and `pretty_json` / `pretty_json_bytes` (written files). Both
   sort keys, keep non-ASCII characters and refuse NaN and infinity. `compact_sha256` is the one hash of a
   JSON value. A ruff ban makes it the only place that may call `json.dumps`.
   - **Scope:** every hash input and every canonical artifact (report, dataset files, manifest, prompt hash,
     cache key, exported schemas). Pydantic's own `model_dump_json`, used for cache *storage* of LLM
     responses and for printing configuration, is out of scope: it is not hashed and is not an artifact.
2. **Typed errors with stable codes** (`common/errors.py`). Every exception the package raises on purpose
   subclasses `BccError` and declares its own `code` (`area.what`, e.g. `cache.miss`). Each keeps its stdlib
   base too (`class CacheMissError(BccError, LookupError)`), so every existing `except` still matches.
   - The rule is checked by an architecture test, not by an import-time hook, because core modules may not
     use `__init_subclass__` (the no-registry rule, ADR 0007). The test imports the whole package and fails
     on a missing, inherited, malformed or duplicate code, and on any code missing from
     `docs/error-codes.md` (and the reverse).
3. **Exit codes are an enum** (`ExitCode` in `app/cli`), with values unchanged (2–7). The CLI never exits with
   a bare integer (AST test). `docs/error-codes.md` holds the curated table and the README links to it.
   Which exception maps to which exit code stays per command for now, because each command prints its own
   message; centralising that mapping is deferred to S16.
4. **Logging uses the standard library.** No new dependency. `app/logging_setup.configure_logging(settings)`
   runs once, right after settings load and before anything is wired. It attaches one stderr handler to the
   `bio_claim_check` logger, with `propagate=False`, so stdout stays data only and a host's root handlers never
   see our records.
   - Format: JSON lines by default, `text` for people (`BCC_LOG_FORMAT`). Level `WARNING` by default
     (`BCC_LOG_LEVEL`). Stderr is diagnostic, not an artifact: the same retry warnings as before appear, but
     now as one JSON object per line instead of the bare message, and `BCC_LOG_LEVEL`, previously ignored,
     now takes effect.
   - **Redaction by key, before emission, on a copy.** Any field named like a secret or personal datum
     (`api_key`, `authorization`, `token`, `secret`, `password`, `email`, `contact_email`, `user_agent`,
     `cookie`, any `*_key` / `*_token` / `*_email`; header and camelCase spellings such as `X-Api-Key` or
     `accessToken` are normalised first), at any depth, becomes `[redacted]`. The original record is never mutated. Exceptions log
     their type only.
   - **No timestamps** in log lines: the caller's environment can add them, and our output stays
     deterministic for tests.
5. **Unreported reasoning tokens are `None`, never `0`.** `Usage.reasoning_tokens: int | None`. A sum with an
   unreported side is `None`: a total over calls that did not all report is unknown, not a lower bound.
   `Usage.zero()` is the explicit empty usage. Cost is unchanged, because reasoning is already inside output
   tokens. We never estimate a measured field.
   - **Wire change:** serialised usage now shows `"reasoning_tokens": null` when unreported. No LLM cache
     existed before S09, so nothing stored is affected.

## Consequences

- **Positive:** one place decides the bytes of every hash and artifact; every deliberate failure has a name a
  user can search for; secrets cannot reach logs through structured fields; usage never overstates what was
  measured.
- **Negative:** message text is not scanned for secrets, so code must never format a secret into a message
  (no current call does; a test covers the existing log lines). Exit mapping is still spread over the
  commands.
- **Follow-ups:** S09 codecs report `reasoning_tokens=None` when a provider omits it; S16 centralises the
  exception → exit-code mapping; S21 completes the taxonomy.
