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
| [0013](./0013-canonical-json-errors-logging.md) | Canonical JSON, typed errors with stable codes, and redacted logging | Accepted | How hashes and artifacts are serialised; how failures are named and exit; what may be logged |

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
| [0014](./0014-provider-adapters-and-pinned-models.md) | Provider adapters: pure codecs, pinned models, deterministic retries | Accepted | How a request reaches Foundry; how usage, finish states and failures are read; which models are pinned |
| [0015](./0015-llm-agent-base.md) | One base for every LLM agent | Accepted | How an LLM agent is declared and run; what provenance every agent request carries |
| [0016](./0016-pipeline-events-and-clock.md) | Pipeline events without content, and one injected clock | Accepted | What a run reports while it works; what an event may never contain; where time comes from |
| [0017](./0017-answer-agent-and-deterministic-checks.md) | Answer agents, abstention, and checks code can make without a model | Accepted | How answers are produced and converted; which defects are refused, flagged or reported; how negation is decided and versioned; what a dev answer may see |
| [0018](./0018-run-record.md) | The run record: canonical result, trace, ledger and live-call budget | Accepted | What a run leaves behind; how the run id is derived; how every attempt and its usage is recorded, including failures; how live calls are capped |
| [0019](./0019-llm-verifier-and-live-run.md) | The LLM verifier, the first live `run` and the retraction re-check | Accepted | What the verifier may see; which LLM failures count per pair and which stop the run; model families; declared prompts; the live and dev `run`; re-checking a run's citations for retractions |
| [0020](./0020-challenge-set-and-judge-freeze.md) | The verifier challenge set and the judge freeze | Accepted | How the verifier is checked on dev; the narrow reading of ADR 0008 for authored claims; the judge fingerprint; the freeze that gates the test split |

## Superseded / historical

None yet.
