# ADR 0024 — The proof checkpoint's predeclared go/adjust rule and pair tables

- **Status:** Accepted
- **Date:** 2026-10-25
- **Supersedes / Extends:** extends [ADR 0022](./0022-trap-set-and-outcomes.md) (the counts gain pair
  tables) and [ADR 0023](./0023-model-panel-confirmation.md) decision 5 (reporting)
- **Related:** [ADR 0020](./0020-challenge-set-and-judge-freeze.md) (the judge is frozen)
- **Enforced by:** `tests/arch/test_trap_set.py::test_the_reported_go_adjust_verdict_is_the_one_code_gives` (I80) ·
  `tests/arch/test_trap_set.py::test_every_committed_trap_result_attests_its_set_dataset_and_freeze` (pair
  tables recount, I76) · `tests/unit/app/test_proof_checkpoint.py` ·
  `tests/unit/features/test_traps_counts.py` (pair cases) ·
  `tests/unit/app/test_cli_traps.py::test_verify_writes_an_attempt_and_record_publishes_once`

## Context

The demo track (roadmap) runs the frozen verifier once on dev-v1 and then decides "go / adjust". That
decision was never defined. Defining it after the counts are seen is a forking path: any reading could be
justified afterwards. The design is also paired (ADR 0022 §5): each trap has its own parent. Per-item
counts cannot show whether the verifier tells a trap from its parent, and a person counting pairs by hand
from the JSON would be reporting a number the code did not produce.

dev-v1 is small and a silver standard (ADR 0023): 15 model traps (2 to 6 per kind), 7 rule-floor traps,
16 parents. Any threshold on it is a judgement call, not a statistical test.

## Decision

Both are committed before any trap is verified.

1. **Pair tables.** For each (kind, generator), `TrapCounts.pairs` holds the full table of trap disposition
   by parent disposition (passed, needs_review, flagged, failed), counted by
   `features/traps/counts.py` and recomputed by CI with the rest of the counts (I76).
   - **Discriminated** = trap `flagged` and parent `passed`.
   - A parent shared by a model trap and a rule-floor trap appears in both tables. The tables are
     descriptive, and their pairs are not independent observations.
2. **The go/adjust rule (`app/usecases/proof_checkpoint.py`, policy `adr-0024-v1`).** The verdict is
   **GO** when all four hold, and **ADJUST** otherwise:
   - model traps flagged ≥ 10 of 15;
   - parents passed ≥ 12 of 16 (parent `needs_review` and `failed` count against it);
   - parents flagged ≤ 3 of 16;
   - failed ≤ 2 of 38.

   Rule-floor traps, `exact` and the pair tables are reported but do not decide. The rule is bound to
   dev-v1's sha256, its exact denominators and freeze v2, and refuses anything else (it fails closed
   instead of rescaling). A run under a later freeze needs its own predeclared rule.
3. **What the verdict changes.** Only how S17a and H1 frame the verifier. The full k-of-n tables are shown
   either way.
   - **GO:** the trust report may present these counts as "silver standard, planted, controlled paired
     design, exploratory dev evidence".
   - **ADJUST:** the demo leads with the trace and the reason for each claim, and the counts are shown
     as "the verifier did not meet its predeclared bar".
   - The judge is not tuned on traps either way. A prompt change goes only through a new freeze
     (ADR 0020) via the challenge set. After a new freeze dev-v1 is seen data, which is disclosed.
4. **One record per freeze.**
   - `traps verify --record` refuses, before any call, a set already recorded under the active freeze.
   - Two kinds of failure are handled differently:
     - A **counted** failure (invalid, truncated or filtered output) is an outcome. It stays in the
       denominator and is not rerun.
     - A **transport, provider or cache error** aborts the whole run, and nothing is published. A rerun
       replays the cached calls and makes live calls only for the rest.
   - Every invocation and its printed usage tally go in dev-log S13p.
5. **Budget wording.** `BCC_MAX_LIVE_LLM_CALLS` counts logical calls, at most two per item (76). Transport
   retries inside a call are bounded by the backend policy, are extra, and are reported from the tally.
6. **The stated verdict is checked (I80).** Dev-log S13p states it as `**Verdict (ADR 0024): GO|ADJUST**`.
   CI checks both directions: no verdict line may appear before `traps/results/v2-dev-v1.json` is
   committed, and once it is, the line must be the verdict code recomputes from it.

## Consequences

- **Positive:** the decision cannot be fitted to the numbers. Code produces the verdict and the pair
  reading, and CI checks both. Unfavourable counts are never hidden.
- **Negative / costs:**
  - The thresholds are arbitrary on small n, and a single item can flip the verdict.
  - The rule is specific to dev-v1: a later set needs its own predeclared rule.
- **Follow-ups:**
  - An expert-confirmed dev-v2 (backlog) gets its own rule.
  - Rates and intervals stay with the benchmark (S16).
