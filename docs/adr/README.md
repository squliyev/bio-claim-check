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
| [0007](./0007-ports-are-base-classes-rules-describe-kinds.md) | Ports are base classes, backends sit beside them, and rules describe kinds | Accepted | What a port looks like; where backends and drivers go; why a new slice needs no rule edits |

## Evidence

| ADR | Title | Status | Resolves |
|---|---|---|---|
| [0005](./0005-quote-location-fails-closed.md) | Quote location fails closed; no fuzzy pass | Accepted | When quoted evidence counts as found in the abstract |
| [0006](./0006-two-axis-verdict-and-disposition.md) | Two-axis verdict, one disposition, and the overstatement taxonomy | Accepted | What a verdict means; how pairs and claims are counted; what a rule pack is |
| [0008](./0008-citable-sources-medline-abstracts.md) | Citable sources: MEDLINE abstracts, identity `MED:<pmid>` | Accepted | Which records a claim may be checked against; how a paper is identified; Europe PMC terms |
| [0009](./0009-cache-and-replay.md) | Cache and replay: raw responses keyed by request; read-only fails closed | Accepted | How a run is reproduced without the network; what a cache miss means in replay |
| [0010](./0010-evaluation-corpus-and-split.md) | Evaluation corpus: pre-registered sieve, trial clusters and a held-out split | Accepted | How eligible abstracts are chosen and split so dev tuning never sees test findings |
| [0011](./0011-sieve-v2-and-sealed-dataset.md) | Sieve v2, own-split pools and the sealed dataset | Accepted | Which rules admitted each candidate; how any edit to the frozen dataset becomes visible; how test ids stay out of the code |

## Model calls

| ADR | Title | Status | Resolves |
|---|---|---|---|
| [0012](./0012-llm-engine-runner-and-cost.md) | LLM engine: one runner, one repair, a complete cache key and honest cost | Accepted | What every model call does, in which order; how repeats, failures and money are counted |

## Superseded / historical

None yet.
