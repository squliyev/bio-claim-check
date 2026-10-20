# Architecture decision records

**Consult this index first.** Before changing structure, dependencies or how results are produced, check
whether a decision already covers it. If your change contradicts one:
1. Write a new ADR that supersedes it.
2. Do not edit the old ADR's decision.

Each ADR names how it is **enforced**: a lint rule, an import contract or a test. The full map of
invariants is in [`../invariants.md`](../invariants.md). New ADRs start from [`template.md`](./template.md).

**Status legend:** Proposed · Accepted · Deprecated · Superseded by NNNN

## Foundations

| ADR | Title | Status | Resolves |
|---|---|---|---|
| [0001](./0001-tooling-and-configuration.md) | Tooling and configuration | Accepted | Reproducible environment; one place reads configuration; no secrets in git |
| [0004](./0004-no-agent-framework.md) | No agent framework | Accepted | Exact, readable, replayable model requests |

## Architecture

| ADR | Title | Status | Resolves |
|---|---|---|---|
| [0002](./0002-rings-ports-composition-root.md) | Rings, slices, ports and a composition root | Accepted | Where code goes; who may import whom |
| [0003](./0003-structure-in-code-judgement-in-llm.md) | Structure in code, judgement in the LLM | Accepted | Which decisions a model may make |

## Superseded / historical

None yet.
