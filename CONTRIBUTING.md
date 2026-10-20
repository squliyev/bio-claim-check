# Contributing

Thank you for helping. There are two ways to contribute, and **the first needs no code**.

## 1. Contribute domain knowledge (no code needed)

The checker is only as good as its knowledge of how papers get misread. If you know a way findings in
your field are commonly overstated, open a **"New misreading rule"** issue. Examples: a mouse result
reported as a human effect, a surrogate endpoint reported as a clinical outcome, or a background
sentence cited as the finding. The form asks for:
- your field;
- the misreading;
- one example claim with the exact abstract sentence and its PMID.

Accepted rules go into a rule pack credited to you (`authors:` in the pack and in the release notes). If
you contributed rules at a hackathon or workshop, they are imported as **your own pack**, credited to
you, and you keep authorship.

## 2. Contribute code

```bash
make sync     # locked environment (requires uv)
make hooks    # pre-commit: ruff, pyright, gitleaks
make verify   # must be green before you open a PR
```

- Read [`AGENTS.md`](AGENTS.md); it applies to humans too. Also read the [ADR index](docs/adr/README.md)
  before changing structure.
- Every behaviour change needs a test. Every architecture or method decision needs an ADR.
- Keep PRs small and describe *why*, not only *what*.
- If an AI assistant wrote part of your change, say so in the PR description. You are still responsible
  for every line.

## Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
