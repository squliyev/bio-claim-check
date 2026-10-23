# ADR 0020 — The verifier challenge set and the judge freeze

- **Status:** Accepted
- **Date:** 2026-10-23
- **Supersedes / Extends:** extends [ADR 0011](./0011-sieve-v2-and-sealed-dataset.md) (the test split is
  touched only under a frozen judge) and [ADR 0019](./0019-llm-verifier-and-live-run.md) (the verifier)
- **Related:** [ADR 0008](./0008-citable-sources-medline-abstracts.md), [ADR 0003](./0003-structure-in-code-judgement-in-llm.md)
- **Enforced by:** `tests/arch/test_challenge_attestation.py` (I72) · `tests/arch/test_active_freeze.py` (I73) · `tests/unit/app/test_corpus_audit.py::test_cli_test_split_is_closed_when_the_freeze_does_not_hold` (I74) · `tests/unit/features/test_challenge_score.py` · `tests/unit/app/test_freeze.py`

## Context

The draft of this ADR was committed with the challenge set and the pass rule, before any model saw the
set (commit A of S12b). It was accepted when freeze v1 landed.

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
   - the bytes of a fixed list of judge source files: the prompts and their rendering, the provider
     codecs, the retry and repair loop, quote location, negation, disposition, and the rule pack with its
     parser;
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
8. **The test audit export** (`corpus audit-sheet --split test`) requires the active freeze, recomputed
   (`active_freeze_sha256`). Its sheet header carries the seal and the freeze hash. `apply-audit` checks
   both and stamps the freeze hash as `prompts_sha256`; `--prompts-sha256` is refused for test. Dev is
   unchanged.

   Each sheet lists only its own split's sources. Abstracts may come from any question's cached pool:
   sources are split by cluster, not by question, and the replay keeps only the wanted ids.

## Outcome (S12b)

- **v1 baseline:** `claude-opus-4-8` with the untuned S12a prompt scored 15/16, with 0 unsafe passes and
  0 failures. The rule was met. The only miss, ch04 (`not_in_source` → `overstated`), was flagged, not
  passed.
- **No tuning:** failure analysis of 31 natural dev pairs found no substantive false pass. The set ran
  once; the recorded result is a byte-identical read-only replay.
- **Negation:** all 4 `negated_supported` dev pairs were `claim_shares_negation`. The claim was itself
  negative and correct, so these are safe false blocks. No rule change; this is a backlog item for a
  later ADR.
- **Freeze v1:** judge `7d8d8f76…`, `freeze_sha256` `c8b5383c…`. The implementation review found that
  the first fingerprint (`6d999644…`) missed the request path, so v1 was redone before any tag or test
  audit. The outcomes are unchanged (cache replay).
- **Committed test audits** must carry the `freeze_sha256` of a committed freeze record. CI checks this,
  so a record written outside the CLI is caught (I74).

## Consequences

- **Positive:** the judge cannot change after the freeze without a visible, reviewed step. The test split
  stays untouched until then. The limits of the evidence are stated.
- **Negative / costs:** the attestation is not proof of a run. 16 items are too few for accuracy. Every
  edit to a judge file forces a new freeze.
- **Follow-ups:** repeats and majority vote (S16). Possible changes to the negation or near-match threshold
  after the measured adjudications, each with its own ADR.
