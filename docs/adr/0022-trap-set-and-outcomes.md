# ADR 0022 — The dev trap set and its outcome artifact

- **Status:** Accepted
- **Date:** 2026-10-24
- **Supersedes / Extends:** extends [ADR 0020](./0020-challenge-set-and-judge-freeze.md) (the judge is frozen;
  sets are sealed dev pairs; results are self-reported) and the narrow reading of
  [ADR 0008](./0008-citable-sources-medline-abstracts.md)
- **Related:** [ADR 0006](./0006-two-axis-verdict-and-disposition.md), [ADR 0019](./0019-llm-verifier-and-live-run.md),
  [ADR 0021](./0021-neutral-few-shot-examples.md)
- **Enforced by:** `tests/arch/test_trap_set.py` (I76, I77) ·
  `tests/unit/app/test_traps_usecase.py` (I78 and the leakage regression) ·
  `tests/unit/features/test_traps_models.py::test_ground_truth_is_predeclared` ·
  `tests/unit/app/test_cli_traps.py::test_verify_refuses_a_stale_freeze_before_any_port`

## Context

The frozen verifier has no measured catch rate. The challenge set (16 items) is a sanity check, not a
measure. The demo track's proof checkpoint needs known misreadings with ground truth, on dev only, before
anyone reads a trap outcome. Without a written design, three things would go wrong:

1. The ground truth could be chosen after the outcomes are seen.
2. A model draft could be relabelled as human work.
3. A trap could leak its kind or its parent to the verifier.

## Decision

1. **The set.** `traps/dev-v1.jsonl` holds author-confirmed `TrapItem`s on dev sources only. Each source
   gives:
   - one **parent**: a supported claim in the writer's own words;
   - one **model trap**: the parent rewritten to commit the sampled kind;
   - zero to three **rule-floor traps**, which are direction, operator or dose swaps of the parent,
     applied only when exactly one site matches.

   A trap is kept only if its parent and the trap itself are confirmed. A rejected parent drops its traps.
   The set holds claims only, never abstract text.
2. **Ground truth is predeclared** (`expected_truth`, before any trap is verified):

   | Role | Generator | `expected_disposition` | `expected_label` | `expected_reason` |
   |---|---|---|---|---|
   | parent | model | passed | supported | — |
   | trap | model | flagged | overstated | the sampled kind |
   | trap | rule_floor | flagged | — (contradicted or not_in_source) | — |

3. **The metrics are predeclared.** All of them are exploratory on dev.
   - **Caught:** a trap's disposition is `flagged`.
   - **Exact:** the label equals the expected label, and the reason equals the expected reason when one is
     declared.
   - **False alarm:** a parent's disposition is `flagged`.

   `needs_review` and `failed` have their own columns and stay in every denominator. A failed trap is not
   caught.
4. **Origin is never relabelled.** Every item has:
   - `origin = model` and `origin_id` = the writer deployment;
   - `confirmed_by = author`.

   `pair_id` links a trap to its parent. Ids are opaque: `t` + 11 hex characters of
   `sha256(salt | source | role | rule)`.
5. **One call drafts both claims. This is a controlled paired design, not naturalistic spin.** The pairing
   favours lexical contrasts. The audit sheet shows no model rationale, and the author decides each row
   separately. This limit is stated wherever trap outcomes are reported.
6. **Sampling is deterministic and dev only.**
   - The scored kinds are `background_as_result`, `correlation_as_causation`, `nonsignificant_as_effect`,
     `preclinical_to_clinical` and `certainty_inflation`.
   - Each eligible source (dev, not excluded, ranked within `pool_hits` of a dev question) goes to its
     scarcest candidate kind.
   - Within a kind, sources are taken in salted-hash order, one per cluster.
   - A larger `--per-kind` extends the same order.
   - A kind with fewer eligible sources than `--per-kind` gets all it has, and the run reports the
     shortfall. Only a kind with none is refused, before any call. On the sealed dev set
     `background_as_result` has 9 eligible sources (18 candidates, 9 within a pool), so its target is
     capped at 9 drafts (maintainer, 2026-10-24).
   - The one-pass assignment can leave a kind short that a full matching would fill. It is kept because a
     matching would reorder picks as `--per-kind` grows and break the cache-hit top-up.
   - Sieve candidates are not labels: the author's decision is the eligibility check.
7. **A pure validity gate runs before the sheet.** It rejects a claim that:
   - is over 30 words;
   - repeats its parent;
   - shares an 8-word run with the abstract (copying);
   - shares a 6-word run with any rule-pack example claim or excerpt (contamination; ADR 0006 follow-up).

   CI recomputes only the contamination check. CI has no abstracts, so close paraphrase is the author's
   call in the sheet.
8. **The narrow reading of ADR 0008 is extended.** A model-drafted claim of at most 30 words that passed the
   copy gate and that the author confirmed as not a close paraphrase may be committed, like an
   author-written challenge claim. **The maintainer should confirm this reading.**
9. **The audit is bound to its draft.** The sheet carries the draft's sha256. `apply-audit` refuses a sheet
   from another draft, and any added, missing, duplicated, edited or undecided row, or a rejection
   without a reason. It also refuses a row whose abstract no longer hashes to its sealed hash, and a set
   that CI would reject. CI recomputes everything a hand edit could change without the abstract:
   - the pool rank of the source;
   - the kind, which must be a scored sieve candidate of the source;
   - each rule-floor claim, which must be exactly the mutation of its parent.
10. **Judging follows the challenge pattern.**
    - `traps verify` refuses unless this code is the active freeze, recomputed.
    - It checks the budget before any call: twice the items, for a call plus a repair.
    - The verifier receives `Claim(id, text, cites)` only. Kind, role, pair and ground truth never leave
      the use case (I69).
    - The output, `TrapResult`, records the set hash, the corpus seal, the judge hash, the verifier and
      `writer_family_flag`, with one `PairOutcome` per item and the counts.
    - `--record` publishes `traps/results/<active freeze>-<set>.json` once. There is no `--name`: the
      command already runs only under the active freeze.
    - CI recounts the result from its outcomes. It also checks the corpus seal, and the judge hash and
      verifier against the freeze record named in the file name. Finally, it recomputes the writer-family
      flag from the model catalog.

    Like the challenge result, this is self-reported consistency, not proof that a model ran.
11. **No tuning on trap outcomes.** The judge is frozen; a change goes through a new freeze and its ADR.

## Consequences

- **Positive:**
  - Catch rates per kind with predeclared truth and metrics.
  - Parents give a false-alarm subset.
  - Every step from draft to set to result is bound by a hash and recomputed in CI where it can be.
- **Negative / costs:**
  - The paired design overstates how separable real spin is.
  - The rater is the author alone.
  - Trap writer `gpt-6.1-sol` is the same deployment as the answerer. It is not the verifier's family; if
    it were, the result would carry `writer_family_flag`.
  - Rule-floor traps test literal reading, not spin.
- **Follow-ups:**
  - Test-split traps need a later ADR, the maintainer's test audit and the active freeze.
  - Surrogate traps wait for H1.
  - A second writer family waits for Kimi (A10).
  - Repeats and intervals wait for S16.
