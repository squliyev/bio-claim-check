# bio-claim-check

> **Does this agent's answer hold up?** An open-source claim checker for life-science agents.

`bio-claim-check` answers a research question from Europe PMC abstracts, then checks every claim against
the paper it cites. Each claim is labelled *supported*, *overstated* (with a reason), *unsupported* or
*not in source*. Planted traps, such as a mouse result presented as a human effect or a trial's
background sentence cited as its finding, measure what the verifier actually catches.

**Status: pre-alpha, under active development.** Nothing here is a validated result yet.

## What it is not

- Not a fact-checker for papers: it checks whether a *claim* is faithful to the *abstract it cites*.
- Not a substitute for reading the paper: abstracts omit caveats found in the full text.

## Quick start (development)

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13.

```bash
make sync            # locked environment
make hooks           # pre-commit: ruff, pyright, gitleaks
cp .env.example .env # fill in locally; .env is git-ignored
make verify          # lint + strict types + offline tests
uv run bio-claim-check --version
uv run bio-claim-check config   # validates settings, secrets redacted
```

With Docker:

```bash
docker compose run --rm app bio-claim-check --version
```

## License

Apache-2.0 (license file added in the next milestone).
