# ADR 0016 — Pipeline events without content, and one injected clock

- **Status:** Accepted
- **Date:** 2026-10-22
- **Supersedes / Extends:** Amends 0007 §8 (no wall clock: one named exemption); extends 0013 (logging)
- **Related:** 0002, 0012, 0015
- **Enforced by:** `tests/unit/app/test_event_union.py` · `tests/unit/engine/test_events.py` · `tests/unit/engine/test_llm_runner_events.py` · `tests/arch/test_event_content.py` · `tests/contract/test_event_sink_contract.py` · `tests/contract/test_clock_contract.py` · `tests/arch/test_ruff_bans.py::test_the_system_clock_is_the_one_wall_clock_exemption` · `tests/arch/test_port_guards.py::test_leaf_packages_import_only_common` · ruff `TID251`

## Context

From S09 on, runs make real, paid calls. They must be observable from the first one: which agent, which
model, which attempt, how many tokens, why it failed. Events are also where secrets and abstract text leak
most easily. And events need a time, which the "no wall clock in src" rule (ADR 0007 §8) forbids reading
directly.

## Decision

1. **Vocabulary.** `engine/events` (a `[LEAF]`: imports only `common`) holds `PipelineEvent` (`type`
   literal, `at: AwareDatetime`) and its subclasses: `StageStarted/Finished/Failed` (+ `is_terminal`),
   `LlmCallStarted/Finished`, `LlmRepairRequested`, `LlmCallFailed`, `LlmRetryScheduled`. LLM events carry
   `ModelRef` (provider, deployment, model version) and the `agent` name.
2. **Closed union.** `app/events.py` assembles `AnyPipelineEvent` (discriminated on `type`, adapter `PIPELINE_EVENT`) and
   `parse_event`; `make schemas` writes `schemas/pipeline_event.schema.json`. A parity test proves every
   subclass is in the union exactly once (I58). Domain events join it in S10+.
3. **No content (I59).** Events carry ids, counts, codes, hashes (`request_hash` = the LLM cache key, `prompt_sha256`) and
   validation locations only: never message text, payload, prompt variables, model output, endpoints or
   keys. A location segment the output schema does not declare (a key the model invented, a dict key) is
   written as `<undeclared>`, here and in error text.
4. **Emitters (I60).** `LlmRunner` emits one `LlmCallStarted` per logical attempt, then one `LlmCallFinished`
   once a response exists (its usage is what this attempt's live call was billed, or the stored usage on
   a cache hit),
   `LlmRepairRequested` per repair, and `LlmCallFailed` before raising any `BccError` (including client
   errors, re-raised unchanged). Backends emit `LlmRetryScheduled` per transport retry. Agents emit stage
   events. Components take `emitter: EventEmitter | None`; `None` is silent.
5. **Sinks.** `BaseEventSink` with `InMemoryEventSink` (tests) and `LoggingEventSink` (stderr through the
   ADR 0013 logger). The `events.jsonl` sink, run-level events, manifest and ledger stay in S11.
6. **Volatile.** Events are never part of a canonical artifact or a cache key; `LlmResponse` stays time-free.
7. **One clock.** `common/base_clock.py` (`BaseClock.now()` → aware UTC) with `scripted_clock.py` and
   `system_clock.py`. `system_clock.py` is the **only** module that reads the wall clock: one ruff `TID251`
   per-file exemption, pinned by a test. It sits in `common`, not `engine`, because the leaf events package
   and the `engine/llm` backends both need it. `EventEmitter(sink, clock)` stamps `at`.

## Consequences

- **Positive:** every paid call is visible with its usage and attempt; a sentinel test proves no content
  leaks; replay stays byte-identical.
- **Negative / costs:** one wall-clock exemption to watch; events only reach stderr until S11.
- **Follow-ups (binding):** S11 writes `events.jsonl` through a new sink, adds run events, and builds the
  ledger from `LlmCallFinished`. S11 also closes the spend gap: a client error the runner re-raises
  unchanged does not yet carry the spend of earlier attempts, and a possibly billed failure (timeout,
  unexpected response) is not yet counted as unmeasured (backlog A14). S17 reads events through `parse_event` (see the S17 note in the backlog).
