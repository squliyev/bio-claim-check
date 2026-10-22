# ADR 0012 — LLM engine: one runner, one repair, a complete cache key and honest cost

- **Status:** Accepted
- **Date:** 2026-10-22
- **Supersedes / Extends:** Extends 0007 (ports and extension points) and 0009 (cache and replay)
- **Related:** 0003, 0004
- **Enforced by:** `tests/unit/engine/test_caching_llm_client.py::test_every_request_shaping_field_changes_the_key` · `tests/unit/engine/test_caching_llm_client.py::test_repeats_are_distinct_provider_calls_and_replay_makes_none` · `tests/unit/engine/test_llm_runner.py` · `tests/unit/engine/test_llm_usage.py` · `tests/unit/engine/test_llm_messages.py::test_invalid_role_shapes_are_rejected` · `tests/unit/app/test_build_models.py` · `tests/contract/test_llm_client_contract.py` · import-linter `engine-is-feature-agnostic`

## Context

Every verdict, answer and trap will come from a model call. Structured-output code usually goes wrong in
the same few places: repeats that silently hit one cache entry (zero variance), repair loops that retry
forever or retry a truncation, failed attempts whose cost disappears, an unknown price shown as $0, and a
deployment name that quietly points at another model. A reviewer must be able to read one file and know
exactly what a call does.

## Decision

1. **One runner, fixed order** (`engine/pipeline/llm_runner.py`). Feature-owned processors plug in at two
   extension points; the list and its order are assembled in `app`, never by registration.

   ```mermaid
   flowchart LR
     A[request processors<br/>feature-owned, S10/S12] --> B[schema from the output type]
     B --> C[client call<br/>CachingLlmClient → backend]
     C --> D[record spend]
     D --> E{finish reason}
     E -- content_filter / length --> X[LlmCallError, no repair]
     E -- stop --> F{validate}
     F -- invalid, 1st attempt --> R[append reply + one repair turn] --> C
     F -- invalid, 2nd attempt --> X
     F -- valid --> G[typed response processors<br/>evidence, negation: S10/S12]
   ```
   - Spend is recorded **before** anything can fail, and every `LlmCallError` carries the spend of all its
     attempts.
   - Only a validation error (including invalid JSON) earns **one** repair. Truncation and content filters
     fail at once: repeating them would fail the same way. Other exceptions propagate unchanged.
   - The response schema is derived from the output type, so the schema sent and the type validated cannot
     disagree. Response processors only ever see validated output.
   - Errors and the repair turn carry validation locations and types only, never validator messages or
     input values, so model- or abstract-controlled text cannot leak into logs or back into the prompt.
   - Processors cannot change what the runner owns. A request processor may not change the model,
     responses or spend; a response processor may change only the payload. The runner checks after each
     one and raises `ProcessorContractError`.
2. **Payload vs request.** An `Invocation` keeps the domain input (`payload`) apart from the `LlmRequest`,
   the only thing a provider sees. This is the code-level basis for context isolation (S12).
3. **Complete cache key.** The LLM key covers model identity (provider, deployment, pinned model version),
   messages, params, response schema and name, seed and `repeat_idx`. Provenance fields (prompt reference,
   cache-hit flag) are excluded: a prompt change already changes the messages. Repeats are therefore distinct
   provider calls, and a read-only replay needs no provider client at all.
4. **First write wins, honestly billed.** When two writers race, the run returns the stored response
   (ADR 0009) but bills the usage of the call it actually made.
5. **Measured tokens, honest money.** `Usage` is what the provider reported, never estimated; reasoning
   tokens are inside output and cached input inside input, so nothing is counted twice. Prices are
   `Decimal`, finite and non-negative, dated and sourced, and entered by the user. No price means cost
   `None` ("unpriced"), never 0; one unpriced live call makes the run's cost unknown. Cache hits count as
   replayed calls and add no cost. A local token estimator is deferred to the pre-flight cost estimate
   (S16/S19).
6. **Fail at wiring.** The engine owns `ModelSpec`/`ModelCatalog` (unknown deployment or duplicate → error,
   no fallback values); `app/models.py` owns our deployments. `build_models` resolves every role and, outside
   read-only replay, requires each role's provider settings, naming the role that lacks them.
7. **Role shape.** A request is an optional single system message, then strictly alternating user and
   assistant turns, ending with user. This is what every provider accepts, and the repair turn keeps it.

## Consequences

- **Positive:** repeats measure real instability; a run's cost is exactly what it paid, or visibly unknown;
  one file explains every structured call; a read-only replay works with no provider settings.
- **Negative / costs:** one repair may be too few for a weak model; that shows up as counted
  `invalid_output` failures rather than being hidden. Providers whose usage reports reasoning outside output
  must be normalised by their codec.
- **Follow-ups (binding):** S09 codecs normalise each provider's raw usage to this contract, with a test per
  shape. S12 maps `LlmFailureKind` to `FailureKind`. S16/S19 add the versioned local token estimate for
  pre-flight cost. Prices are added to `app/models.py` by the user, with date and source.
