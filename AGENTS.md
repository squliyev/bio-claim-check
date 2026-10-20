# Instructions for coding agents (and humans)

This is research software whose numbers other scientists may rely on. Correctness and honesty come
before speed.

## Gate

- Run `make verify` before every commit; it must be green. It runs ruff, ruff format, pyright strict,
  `lint-imports` and the offline tests.
- Never weaken a check to make it pass. Do not add `# noqa`, `# pyright: ignore`, or loosen a contract
  without a one-line reason next to it.

## Architecture (docs/adr/0002)

- Rings point inward: `common ← engine ← features ← infrastructure ← app`. Only `app` wires concrete
  classes together.
- Feature slices never import each other; shared models go in `features/contracts`. Code that combines
  slices goes in `app/usecases`.
- A slice grows in this order:
  1. `ports.py` (interfaces).
  2. `models.py`.
  3. Pure logic.
  4. `fakes.py`.
  5. A shared contract suite in `tests/contract/`.
  6. Only then a real adapter in `infrastructure/`.
- Deterministic modules (checks, statistics, agreement) never import `engine.llm` (docs/adr/0003).
- A new slice must be added to the `slices` import-linter contract; a parity test reminds you.

## Code conventions

- Every module docstring starts with `[RING:<ring>]` or `[RING:<ring>/<slice>]`, then explains **why**
  the module exists, what it replaced if anything, and what it must **not** do. Deterministic modules
  say "No LLM is involved in this module."
- Configuration is read only in `app/settings.py`. Everything else receives a `Settings` object.
- Test helpers live in `tests/support/`, start with `[TEST SUPPORT]`, and are never imported from `src/`.
- No blind `except`, no `print` (use the logger), no relative imports.

## Decisions and docs

- A load-bearing decision needs a new ADR from `docs/adr/template.md`, with an `Enforced by:` line, and
  a row in `docs/adr/README.md`.
- A new invariant needs a row in `docs/invariants.md`, with its guard and test.
- At the end of a work session, update `docs/backlog.md` and write `docs/dev-log/Sxx.md`.

## Never

- Commit secrets, real endpoints, `.env` files or personal data. gitleaks will block most, but not all.
- Copy code from other codebases. Reimplement ideas and credit them where appropriate.
- Report a number the code did not produce, or describe author-labelled data as expert-labelled.
