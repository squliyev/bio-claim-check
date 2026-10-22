# ADR 0010 — Evaluation corpus: pre-registered sieve, trial clusters and a held-out split

- **Status:** Accepted
- **Date:** 2026-10-21
- **Supersedes / Extends:** Extends 0008
- **Related:** 0003, 0006, 0009
- **Enforced by:** `tests/unit/app/test_build_corpus.py` (golden bytes, cluster and held-out rules) · `tests/unit/features/test_corpus_eligibility.py` · `tests/unit/features/test_corpus_clusters.py` · `tests/unit/contracts/test_corpus.py` · import-linter `slices`, `no-llm-in-deterministic-code`, `pure-modules-import-no-drivers`

## Context

Every later number (catch rate, false-alarm rate, baselines) is computed on a set of abstracts with
planted overstatements. Three things can make those numbers meaningless without anyone noticing:

1. **Tuning on the test set.** One person writes the prompts, the rule packs and the traps. If that
   person has read the test abstracts, "held out" is a claim nobody can check.
2. **Leakage through related papers.** A trial's main paper in test and its secondary analysis in dev
   lets dev tuning see test findings.
3. **Unfair traps.** A `preclinical_to_clinical` trap on a human trial, or a `nonsignificant_as_effect`
   trap on an abstract with no null result, measures nothing. Picking eligible abstracts by eye after
   seeing them is adaptive selection.

## Decision

- **Spec first.** Questions, Europe PMC search strings, the cutoff date, salts, the dev fraction, the
  trap kinds, the sieve version and the audit size live in one strict YAML spec (`CorpusSpec`). It is
  committed on its own before any pool is fetched (the pre-registration commit, S07b).
- **Pool.** For each question: the citable records (ADR 0008) among the first `pool_hits = 100` Europe
  PMC hits for `(<search>) AND FIRST_PDATE:[1900-01-01 TO <cutoff>]`, in relevance order. No paging and
  no top-ups; a short pool is recorded, not fixed. A source retrieved by several questions is one row
  with every `(question, rank)`. The same source with different metadata under two questions stops the
  build (`PoolConflictError`).
- **Never candidates** (kept in the pool, flagged with `NeverReason`): retracted papers; reviews,
  systematic reviews and meta-analyses; records with **no** publication types (unknown cannot prove "not
  a review"); and, for the MeSH-based kinds only, records with `mesh_headings = None` (not indexed yet
  cannot prove "no Humans tag").
- **Sieve v1** (`features/corpus/eligibility.py`, no LLM, ADR 0003), four kinds. *Extended by
  [ADR 0011](./0011-sieve-v2-and-sealed-dataset.md): sieve v2, five kinds, is what built the dataset.*

  | Kind | Rule | Evidence |
  |---|---|---|
  | `preclinical_to_clinical` | `animals_not_humans`: MeSH Animals and not Humans; or `in_vitro`: a cell-line/in-vitro MeSH term and no clinical-design MeSH or clinical publication type | MeSH, publication types |
  | `correlation_as_causation` | `observational`: cohort, prospective, retrospective, case-control or cross-sectional MeSH, or type Observational Study; and no RCT or Clinical Trial\* type | MeSH, publication types |
  | `nonsignificant_as_effect` | `null_result`: a sentence matching "no/not (statistically) significant", "did not differ/improve/reduce/change/increase/decrease" or `p >/=/≥` a value ≥ 0.05 (the whole number is read, so `0.049` is not a hit) | sentence span |
  | `certainty_inflation` | `closing_hedge`: one of the **last two** sentences contains may/might/could/suggest/potential/possible/warrant/further studies | sentence span |

  Sentence splitting is conservative and private to the sieve (no split after e.g., i.e., vs., et al.,
  Fig., approx., ca.; decimals never split). `surrogate_as_clinical` is the next kind (backlog). A rule
  change is sieve v2 and a new ADR, never an edit after the pool is seen.
- **Clusters.** Papers are joined (union-find) by NCT ids in the title or cleaned abstract
  (case-insensitive, upper-cased, several per paper) and by normalised title (casefold, alphanumerics
  only). The cluster id is its smallest source id in numeric order.
- **Split.** A cluster containing any source retrieved by a held-out-domain question is **test**.
  Otherwise it is **dev** iff `int(sha256(f"{split_salt}:{cluster_id}")[:16], 16) / 2**64 < dev_fraction`.
  The salt is public, so anyone can recompute the split and nobody can steer it. The held-out domain is
  statins in Alzheimer's, Parkinson's and dementia; its questions are all test.
- **Audit order (S07b).** The author confirms a fixed `audit_n = 50` test candidates per kind (or all, if
  fewer), in ascending `sha256(f"{audit_salt}:{kind}:{source_id}")` order. A fixed N keeps the Wilson
  interval on sieve precision valid; reviewed rows must be exactly the first N. Labels are
  "author-confirmed".
- **Held-out procedure.** Prompt and rule-pack tuning (S10, S12) uses only dev sources; retrieved papers
  outside dev are dropped and counted. The test audit happens only after the `prompts-frozen-v1` tag (end
  of S12), and the protocol (S15) checks the prompts hash against it.
- **Files.** `dev/sources.jsonl`, `test/sources.jsonl`, `questions.jsonl` and `manifest.json`: canonical
  bytes (sorted keys, UTF-8, rows in numeric id order). They hold ids, metadata, offsets and hashes, and
  **never abstract text** (publisher copyright, ADR 0008). Each `questions.jsonl` row records the exact
  query sent, the pool size and a hash of the ranked pool. The manifest holds the sha256 of every data
  file and of the spec, the declared fetch date, the tool version, candidate counts for every
  domain × split × kind cell (zeros included) and the NLM notice. It is published last; existing files
  are never overwritten (`publish_once`).

## Consequences

- **Positive:** the split is recomputable from public inputs; trial-level leakage is closed; every
  candidate carries the rule and evidence that admitted it; a rebuild from the same spec, cache, tool
  version and declared date is byte-identical (I37).
- **Negative:**
  - Byte-identical rebuilds hold on the author's machine (the cache is not redistributed). Others get
    PMIDs, `abstract_sha256`, query strings and per-pool hashes, and `hydrate` (S23) reports drift.
  - The sieve is high-recall by design and its precision is only measured on the test audit. The
    MeSH-cue baseline (S14) shares the sieve's signal; paired E1/E2 mostly cancels this, and the data
    card says so.
  - Title clustering misses near-duplicate titles; shingling is out of scope.
- **Follow-ups:** S07b (live build, seal, guards, audit tooling, data card); `surrogate_as_clinical`
  (backlog); `hydrate` (S23).
