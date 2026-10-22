# ADR 0011 — Sieve v2, own-split pools and the sealed dataset

- **Status:** Accepted
- **Date:** 2026-10-21
- **Supersedes / Extends:** Extends 0010 (replaces its "Sieve v1" table; every other decision in 0010 stands)
- **Related:** 0003, 0008, 0009
- **Enforced by:** `tests/unit/features/test_corpus_eligibility.py::test_exclusions` · `tests/unit/features/test_corpus_eligibility.py::test_baseline_balance_is_not_a_null_result` · `tests/unit/features/test_corpus_eligibility.py::test_prior_finding` · `tests/unit/app/test_build_corpus.py::test_each_question_counts_only_the_pool_sources_in_its_own_split` · `tests/unit/app/test_build_corpus.py::test_a_changed_response_changes_its_hash_and_no_other` · `tests/arch/test_dataset_seal.py::test_the_committed_dataset_is_intact_and_sealed` · `tests/arch/test_dataset_seal.py::test_no_tracked_file_outside_datasets_names_a_test_id` · `tests/unit/features/test_corpus_audit_sheet.py`

## Context

ADR 0010 fixed the corpus design with sieve v1 and said any rule change is "sieve v2 and a new ADR". Before
the live fetch, three problems with v1 surfaced from an AI consult on draft pools and the S07b plan review:

1. Trial **protocols** were treated as trials, although they report no results to overstate.
2. The null-result rule fired on **baseline-balance** sentences ("groups did not differ at baseline"),
   which say nothing about an effect.
3. `background_as_result` (stating prior work as the paper's own finding) had no candidates, although it
   is one of the headline traps.

The plan review also found that `HR|OR|RR` under a case-insensitive pattern matches the word "or", that
a dev question's pool can contain test-assigned papers, and that nothing yet proved the committed bytes
are the bytes that were built.

**Sieve v1 was a draft that never ran on data.** No pool had been fetched under it, so v2 is still a
pre-registered rule set: it was committed alone and tagged `prereg-corpus-v1` before the first fetch.

## Decision

- **Sieve v2** (`SIEVE_VERSION = 2`, `features/corpus/eligibility.py`, no LLM, ADR 0003), five kinds:

  | Kind | Rule | Change from v1 |
  |---|---|---|
  | `preclinical_to_clinical` | `animals_not_humans` / `in_vitro` | unchanged |
  | `correlation_as_causation` | `observational` | unchanged |
  | `nonsignificant_as_effect` | `null_result` | a sentence that pairs a balance term (baseline, demographic, characteristics) with a group term (group, arm), or says "with respect to age/sex/…", is skipped. A later real null sentence in the same abstract is still a hit |
  | `certainty_inflation` | `closing_hedge` | unchanged |
  | `background_as_result` | `prior_finding` (new) | one of the first three sentences has a prior-evidence cue ("has been shown", "previous studies", "evidence suggests", …) **and** an effect verb (reduce, improve, protect, associated with, …), **and** a later sentence has a results cue ("we found", "results showed", "significantly", "compared with", a p value, or a **case-sensitive, numeric** `HR`/`OR`/`RR` such as `OR 1.4`, `HR=`, `RR (95%`) |

- **New never-reason `protocol`:** publication type "Clinical Trial Protocol" blocks every kind.
- **Own-split pools.** A question's evaluation pool is its ranked pool filtered to **its own split**.
  `questions.jsonl` records both `pool_size` and `split_pool_size`, plus the sha256 of the ranked pool
  and of the raw API response for the exact query. Unanswerability refers to the filtered top 10.
  S10/S12 tuning drops every non-dev source and counts the drops.
- **Seal.** `datasets/SEALED` is one line: the sha256 of `manifest.json`. The manifest hashes every data
  file **and** the raw `corpus.yaml` bytes, so one hash seals everything. `corpus seal` writes it once
  and refuses a different value. `dataset_problems` (`features/corpus/seal.py`, pure) lists every reason
  the dataset is not intact: seal and hash mismatches, missing or extra files, rows in the wrong split
  file, duplicate sources, a cluster in both splits, a held-out source in dev, ranks for unknown
  questions, questions that disagree with the spec, and candidate counts that do not recompute. CI runs
  it on the committed dataset; `corpus verify` runs it locally. `README.md` and `audit/*` are the only
  extra files allowed.
- **No test ids outside `datasets/`.** An arch guard scans every git-tracked text file outside
  `datasets/` for a test-split PMID (`MED:<n>`, or a bare number only by exact membership in the test
  PMID set) and for test question ids.
- **Audit tooling (dev only for now).** `audit_order` is the public salted-hash order of ADR 0010;
  `parse_decisions` accepts exactly the first N rows, `confirm`/`reject`, and a reason for every
  rejection. Each `AuditRecord` carries the corpus seal and is published once. The **test** export is
  not built until the prompt freeze exists (S12), and it will compute the prompts hash itself.
- **Dev pilot for the new kind, declared before the build:** the dev `prior_finding` candidates are
  judged against "own results do not establish the background statement"; precision below 60 % drops the kind from scoring (never a regex tweak), and the drop is
  disclosed. **Result:** 12/18 confirmed (67 %, Wilson 95 % CI 0.44–0.84) by one AI agent (single
  judge; the author did not review the items); per-item record in
  `docs/pilots/background_as_result-dev-v1.csv`. The kind stays. An earlier unrecorded tally (16/18)
  is withdrawn.

## Consequences

- **Positive:**
  - Every rule change happened before any data was seen, and the tag proves the order.
  - One hash makes any edit to the spec, the splits or the questions visible, and CI fails on it.
  - Test ids cannot leak into prompts, rule packs, tests or docs by accident.
- **Negative / costs:**
  - `prior_finding` precision is measured on dev by one AI judge (n = 18, lower bound 0.44); the test
    audit is the real measurement.
  - Known sieve-v2 regex limits: the null p-value pattern misses `p = 1.0`, and the results cue accepts
    a bare `p =`. Changing either alters candidates, so it needs sieve v3 and a new ADR.
  - The baseline-balance skip can hide a real null that happens to share a sentence with balance terms;
    the tests cover the keywords one by one, not every phrasing.
  - `background_as_result` has few candidates in the GLP-1 domain (dev 4, test 3); its per-kind total
    (test 41) comes mostly from metformin and statins.
- **Follow-ups:** test export and freeze record (S12); test audit and test unanswerable check (author,
  before S13); protocol hashes (S15); `hydrate` (S23).
