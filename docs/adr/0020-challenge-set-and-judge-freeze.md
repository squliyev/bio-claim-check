# ADR 0020 — The verifier challenge set and the judge freeze

- **Status:** Proposed
- **Date:** 2026-10-23
- **Supersedes / Extends:** extends [ADR 0011](./0011-sieve-v2-and-sealed-dataset.md) (the test split is
  touched only under a frozen judge) and [ADR 0019](./0019-llm-verifier-and-live-run.md) (the verifier)
- **Related:** [ADR 0008](./0008-citable-sources-medline-abstracts.md), [ADR 0003](./0003-structure-in-code-judgement-in-llm.md)
- **Enforced by:** `tests/unit/features/test_challenge_score.py` · `tests/unit/app/test_challenge_usecase.py` · `tests/unit/app/test_freeze.py` · `tests/unit/app/test_cli_challenge.py` (the attestation and active-freeze tests follow in later S12b commits)

## Context

This ADR was drafted in the same commit as the challenge set and pass rule, before any model saw the set.
It becomes Accepted when the freeze lands.

S12a shipped the LLM verifier with untuned wording. Before anyone looks at the test split, we need three
things:

1. A small, honest check that the verifier behaves on dev.
2. A guard so the judge cannot change silently.
3. One fingerprint of everything that judges claims, frozen before test.

Abstracts cannot be committed (ADR 0008), and CI has no cache and no keys, so CI cannot call a model.

## Decision

1. **The challenge set.** `challenge/dev-v1.jsonl` holds 16 curated `ChallengeItem`s: 4 per label, 2 per
   dev question, and at most 1 per source. Each item binds its abstract by `abstract_sha256`.
   - Labels are `ai_draft_author_confirmed`: one human rater. An AI blind second rater was also used; it
     is not an expert.
   - The set is a regression and sanity check. It is **not** an accuracy estimate.
2. **The narrow reading of ADR 0008.** A short claim written by the author *about* an abstract (≤ 30
   words, never a copied sentence or close paraphrase) is not abstract text. It may be committed. No
   other abstract-derived text may be: no rationales and no quotes. The maintainer should confirm this
   reading.
3. **The pass rule** is declared in the same commit as the set, before any run:
   - (a) zero unsafe passes;
   - (b) agreement ≥ 3/4, where an overstated item also needs its reason to match;
   - (c) failures plus `ABSENT` evidence ≤ 1/8.

   The label × disposition table, `negated_supported` and `near_located` are reported but not gated.
4. **Tuning stays off the set.** Prompt revisions (at most 3) come only from failure analysis of natural
   dev pairs. The set runs at most twice: the baseline and the final prompt.
5. **The judge fingerprint** (`app/freeze.py`) is the sha256 over:
   - the bytes of a fixed list of judge source files, including the rule pack;
   - the `rapidfuzz` version;
   - the full answerer and verifier `ModelSpec`s.

   Any edit to a listed file changes it. This is fail-closed by design.
6. **The attestation.** `challenge run --record` publishes `challenge/dev-v1.result.json` once. CI checks
   that its challenge and judge hashes match the recomputed values, that every item is a sealed dev pair,
   and that the recomputed score passes.

   This is **self-reported**: it proves consistency, not that a model ran. The trust root is the
   maintainer and the `prompts-frozen-v1` tag. A read-only replay from the local cache reproduces it
   byte for byte.
7. **The freeze.** `freeze/v1.json` records the judge and result hashes. `app/freeze.py` pins its bytes,
   and an active pointer names it. A new freeze needs a new file, a new pin and an ADR.
8. **The test audit export** requires the active freeze, recomputed. Its sheet header carries the freeze
   hash, and `apply-audit` checks it. Dev is unchanged.

## Consequences

- **Positive:** the judge cannot change after the freeze without a visible, reviewed step. The test split
  stays untouched until then. The limits of the evidence are stated.
- **Negative / costs:** the attestation is not proof of a run. 16 items are too few for accuracy. Every
  edit to a judge file forces a new freeze.
- **Follow-ups:** repeats and majority vote (S16). Possible changes to the negation or near-match threshold
  after the measured adjudications, each with its own ADR.
