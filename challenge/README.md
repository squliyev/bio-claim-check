# Verifier challenge set

`dev-v1.jsonl` contains 16 curated (claim, source) items for the LLM verifier. They come only from
**dev** questions and sources. See [ADR 0020](../docs/adr/0020-challenge-set-and-judge-freeze.md).
The recorded result of each freeze is `results/<freeze>.json`: v1 and v2 (the active one, ADR 0021).
The set has run twice, its limit.

## What it is

- It is a **regression and sanity check** of the verifier on dev: 4 items per label (`supported`,
  `overstated`, `contradicted`, `not_in_source`), 2 per dev question, and at most 1 per source.
- It is **curated**, not sampled. A score on it is **not** an accuracy estimate. It says nothing about live
  claims or about the pipeline end to end.

## Provenance

- Each claim is a short statement (at most 30 words) written for this set. It is not a copied sentence or
  a close paraphrase of the abstract. Abstracts are not committed (ADR 0008). Each item binds its abstract
  by `abstract_sha256`, which must equal the sealed entry in `datasets/`.
- `label_source: ai_draft_author_confirmed`: an AI assistant drafted the items and labels, and the
  maintainer confirmed each one. This is a **single human rater** and not an expert panel.
- An AI agent then acted as a blind second rater. It saw the claims and abstracts but not the labels, and
  it agreed on 16/16 labels and on all 4 overstated reasons. That agent is an AI, not a human or an
  expert. After its review, 7 claims were reworded to remove ambiguity. No label changed.

## Pass rule (declared before any model saw the set)

1. Zero unsafe passes: no `contradicted` or `not_in_source` item ends `passed`.
2. At least 12/16 exact agreement. An `overstated` item agrees only when its reason also matches.
3. Counted failures plus `ABSENT` evidence: at most 2.
