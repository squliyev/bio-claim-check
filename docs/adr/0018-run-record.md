# ADR 0018 — The run record: canonical result, trace, ledger and live-call budget

- **Status:** Accepted
- **Date:** 2026-10-23
- **Supersedes / Extends:** supersedes the S05 run-id rule (run id = hash of `report.json`); extends
  [ADR 0012](./0012-llm-engine-runner-and-cost.md) (I44 narrowed) and [ADR 0016](./0016-pipeline-events-and-clock.md)
- **Related:** [ADR 0009](./0009-cache-and-replay.md), [ADR 0017](./0017-answer-agent-and-deterministic-checks.md)
- **Enforced by:** `tests/unit/app/test_run_record.py` · `tests/unit/app/test_answer_dev.py::test_a_read_only_replay_reproduces_the_answer_and_the_manifest_byte_for_byte` · `tests/e2e/test_fake_run.py` · `tests/unit/engine/test_call_tally.py` · `tests/unit/engine/test_llm_runner_events.py` · `tests/unit/engine/test_budgeted_llm_client.py` · `tests/unit/infrastructure/test_line_files.py` · `tests/contract/test_event_sink_contract.py`

## Context

Before S11 a run left only `report.json`, and `answer dev` left nothing. Events lived in memory and were
lost. A failed or cancelled run left no trace, and a paid attempt before a client error dropped out of
the money record (backlog A14). Nothing capped the number of live calls. The S05 run id hashed only the
report, so the same report produced under different models or data had the same id.

## Decision

1. **One root** (`Settings.var_dir`; `run --fake --var-dir`, default `var`):
   - `runs/<run_id>/` holds the artifact (`report.json` or `answer.json`) and `manifest.json`.
   - `events/<UTC start>-<n>.jsonl` holds the trace (`n` = 0..99, exclusive create, fails closed).
   - `ledger.jsonl` is append-only, one row per attempt.
2. **Canonical result.** The artifact and the manifest hold no time, path, host or cache mode. The
   manifest names the command, provenance, package version, the artifact's hash, the inputs (by hash or
   id), the LLM uses (agent, provider, deployment, model version, prompt hash, served model) and the
   rule-pack or dataset-manifest hash. `run_id` = the first 16 hex of sha256(manifest bytes). With the
   same package version, a read-only replay reproduces both files byte for byte.
3. **Publication order.** Nothing is published until the body has finished and the trace has closed
   cleanly. Then the artifact, then the manifest **last** as the commit marker: a folder without a
   manifest is incomplete (if the manifest itself fails to publish, the artifact may remain without it).
   Each file is published once; different bytes under the same name are refused.
4. **Trace.** Every event is streamed into memory first, then into the file (one canonical line per
   event, flushed per line; fsynced on close). The ledger and manifest fold the memory copy, so a
   trace-write failure (`events.write`) cannot lose usage. The trace holds times and cache hits and is
   never compared byte for byte. Durability covers a process crash, not power loss (no parent-dir fsync).
5. **Ledger row:** start and finish time, command, status (`succeeded`, `failed`, `cancelled`), code,
   run id (only on success), trace file name (null if it could not be opened), cache mode (null for
   fake) and usage per model. No question text, path or cost. The code is the `BccError` code,
   `run.cancelled` for an interrupt, or `run.internal` for any other exception. These two are run codes,
   not error classes, and are not listed in `error-codes.md`. The original exception is always
   re-raised; a ledger-write failure exits OUTPUT on success and is only logged while another error
   propagates.
6. **Usage, one fold** (`engine/events/call_tally.py`), named by unit: finished attempts, cache hits,
   failed calls, `unmeasured_attempts` (a failure that may have reached the provider, or a start with
   no terminal event), `transport_retries`, and measured tokens. Unknown usage is never counted as 0.
   `LlmCallFailed.unmeasured` is decided at the `client.complete` call; a cache-write failure after a
   live response (`CacheWriteError`) is unmeasured. This closes A14 through events: I44 is narrowed to
   "every `LlmCallError` carries the spend of all its attempts", and the ledger is the run's money
   record.
7. **Budget.** One `CallBudget` per command, shared by every live client, refuses logical live call
   `n+1` before it is made (`llm.budget_exceeded`, PROVIDER). Cache hits are free. Transport retries are
   bounded by the transport policy and shown in the ledger. `BCC_MAX_LIVE_LLM_CALLS` defaults to 40.

## Consequences

- **Positive:** every attempt leaves one ledger row and, unless the trace cannot be opened, a trace; only
  a success publishes an artifact and manifest; success is recorded only after publication; replay is a
  byte-level check; no paid attempt drops out of the money record.
- **Negative / costs:** the run id includes the package version, so it changes on every release. The
  ledger has no locking (single user) and no tail repair (no reader yet). Start/finish pairing relies on
  the sequential runner.
- **Follow-ups:** cost once prices exist (A13); `runs prune` (S21); a UI reading the trace (S17).
