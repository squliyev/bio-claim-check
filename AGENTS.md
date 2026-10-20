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
- The engine is the feature-agnostic core: it never imports `features` (not even `features.contracts`).
  Features extend engine bases; `app` wires them in. No import-time registries.
- `infrastructure` holds only tiny, generic transport; it never imports `features` or `engine`.
- Only backend modules (and `infrastructure`, `app`) import drivers. Pure modules never do (contract
  `pure-modules-import-no-drivers`). A new runtime dependency must be classified in
  `tests/arch/test_dependency_policy.py`.
- `app.cli` and `app.ui` reach infrastructure only through the container; use cases receive ports.
- No static import cycles, and no module imports its own ancestor package.
- After changing imports between packages, run `make graph` and commit `docs/architecture/*.dot`.
- Feature slices never import each other; shared models go in `features/contracts`. Code that combines
  slices goes in `app/usecases`.
- Ports are abstract base classes (docs/adr/0007): `base_<thing>.py` holds one `Base<Thing>(ABC)`;
  implementations subclass it, mark methods `@override`, and sit beside it as `<prefix>_<thing>.py`.
- A slice grows in this order:
  1. `base_<thing>.py` (the port).
  2. `models.py`.
  3. Pure logic.
  4. `in_memory_<thing>.py` (stores) or `scripted_<thing>.py` (canned judgement).
  5. A shared contract suite in `tests/contract/`.
  6. Only then a backend `<backend>_<thing>.py` beside the base.
- Deterministic modules say "No LLM is involved in this module." and must then be listed in the
  `no-llm-in-deterministic-code` sources; a parity test reads the docstrings (docs/adr/0003).
- A new slice must be added to the `slices` import-linter contract; a parity test reminds you.
- Rules describe kinds, never instances. A new slice, port or backend must pass the existing rules
  without editing them; if a contract or guard must change, write why in the dev-log (or an ADR).
- No wall clock or randomness in `src` (`datetime.now`, `time.time`, `random`, `uuid4`, `os.urandom`, …) and no `importlib.import_module`; inject a
  clock or seed. Canonical artifacts must be byte-identical.

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
