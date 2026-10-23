# ADR 0021 — Few-shot examples off the benchmark's topics, and freeze v2

- **Status:** Accepted
- **Date:** 2026-10-23
- **Supersedes / Extends:** Extends [ADR 0020](./0020-challenge-set-and-judge-freeze.md) (freeze v2 becomes the
  active freeze; v1 is kept as history).
- **Related:** [ADR 0011](./0011-sieve-v2-and-sealed-dataset.md), [ADR 0008](./0008-citable-sources-medline-abstracts.md)
- **Enforced by:** `tests/arch/test_prompt_neutrality.py::test_no_prompt_or_rule_text_names_a_benchmark_topic` (I75)
  · `tests/arch/test_active_freeze.py` · `tests/arch/test_challenge_attestation.py`

## Context

The rule pack's few-shot examples use fictional compounds, so they cannot leak an abstract. But an audit
for prompt overfitting, before any test audit, found that 3 of the 9 example scenarios (6 of 18 examples)
sat on the benchmark's own topics:

- the preclinical_to_clinical example was an Alzheimer's mouse model, as in two test questions;
- the correlation_as_causation example was a colorectal cancer registry cohort, as in dev metformin-q1;
- the population_extrapolation example was in type 2 diabetes.

The rule pack (S04) predates the questions, so this was not tuning on test. Still, examples on the same
topics as the questions can make verdicts easier on exactly those questions, which is where the headline
numbers come from. The prompts themselves and the code were clean: no drug, disease, PMID or question
wording.

## Decision

1. **Re-topic, not remove.** The 6 examples move to topics that appear in no question, no query and no
   source's MeSH metadata, dev or test: gout in rabbits, an asthma registry cohort, and atopic dermatitis
   in teenagers. All 18 examples, the 9 rules and each lesson stay the same. The maintainer confirmed the
   wording. The rule pack is now `0.2.0`.
2. **A guard (I75).** An arch test takes every search term from the queries of all questions and fails if
   any appears in a prompt or in the rendered rules. Generic study vocabulary that the rules must use
   (study designs, model organisms, exposure and population words, a generic end point) is listed in
   `GENERIC`, each with its reason. The old pack fails the guard.
3. **Freeze v2.**
   - The judge changed, so the challenge set ran its second and last allowed time (ADR 0020 §4).
   - Results now live at `challenge/results/<freeze>.json`. v1's result moved there with its bytes unchanged.
   - `freeze/v2.json` is pinned, and `ACTIVE_FREEZE = "v2"`. `freeze/v1.json` stays pinned and unedited.
   - The tag is `prompts-frozen-v2`. `prompts-frozen-v1` stays as history; no test audit used it.

## Outcome

- **v2 challenge result:**
  - `claude-opus-4-8`, judge `9ce2d728…`;
  - **15/16**, with 0 unsafe passes and 0 failures; the rule is met;
  - the outcomes match v1 on every item. The only miss is still ch04 (`not_in_source` → `overstated`),
    flagged, with reason `other` (v1 had `certainty_inflation`).
- The read-only replay was byte-identical.
- `freeze_sha256` is `6e8e57c4…`.

## Consequences

- **Positive:** the few-shot examples can no longer favour our topics, and the guard keeps it so.
- **Negative / costs:**
  - The challenge set is spent: a further judge change needs a new challenge set, or an ADR that accepts
    a third run.
  - The guard only matches exact query terms, so a synonym (for example "memory loss" for dementia)
    would pass it.
- **Follow-ups:** none.
