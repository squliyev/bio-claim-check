# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

- Report it privately through GitHub private vulnerability reporting (**Security → Report a
  vulnerability**). Reports will be acknowledged within 7 days.

In scope:
- Leaking secrets or provider endpoints through logs, reports or exported bundles.
- Prompt injection from abstract text that changes a verdict.
- Unsafe rendering of abstract text in the UI.
- Path traversal in run, cache or annotation storage.

## Supported versions

Only the latest release, and `main` before 1.0, receive fixes.

## Current safeguards

What is in place and tested today:

- Secrets live only in a local, git-ignored `.env`. They are validated once at startup, and the
  `config` command redacts them (tested).
- gitleaks runs before every commit and over the full history in CI, with a project rule against real
  provider endpoints.
- Runtime dependencies are locked with hashes in `uv.lock`. The build backend is pinned to an exact
  version. CI actions are pinned by commit SHA and kept current by Dependabot.
- The container runs as a non-root user. `var/` is the only directory meant for persistent data.

Planned before 1.0: a dependency audit (`pip-audit`), prompt-injection and malformed-output chaos tests,
and escaping of all abstract text in the UI.
