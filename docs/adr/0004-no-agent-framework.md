# ADR 0004 — No agent framework: a thin engine over the official SDKs

- **Status:** Accepted
- **Date:** 2026-10-20
- **Supersedes / Extends:** —
- **Related:** 0002, 0003
- **Enforced by:** convention, reviewed in PRs. Neither LangChain nor LangGraph is a dependency in `pyproject.toml`; a dependency on either requires a new ADR that supersedes this one.

## Context

The pipeline is a fixed sequence: retrieve → answer → check → verify → report. It does not need open-
ended agency, tool routing or long-term memory. What it needs is that every request sent to a model can
be read, cached by content, replayed exactly and attributed to a pinned model version. Frameworks add
layers between our code and the request. They also add changing abstractions and transitive
dependencies, and that makes exact replay and auditing harder.

## Decision

- Call providers through their **official SDKs** (`openai`, `anthropic`) behind our own small `LlmClient`
  port in `engine.llm` (S08).
- Structured output uses each provider's native mechanism:
  - strict JSON schema for OpenAI-compatible endpoints;
  - forced tool use for Claude.
- Results are validated with pydantic.
- Orchestration is plain Python in `app.usecases`.

## Consequences

- **Positive:**
  - Every request is a plain, hashable object.
  - Caching and replay are exact.
  - Fewer dependencies to audit.
- **Negative / costs:**
  - Retries, schema handling and provider differences are our code to write and test.
- **Follow-ups:**
  - S08 engine core.
  - S09 provider adapters with a structured-output support matrix.
