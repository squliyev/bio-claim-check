# Data card: bio-claim-check evaluation corpus (v1)

**Status:** draft, frozen and sealed. No claim labels yet; only the two dev checks in §5. Read this before using any number computed on it.

| | |
|---|---|
| Location | [`datasets/`](../datasets/README.md) |
| Seal | `datasets/SEALED` = sha256 of `manifest.json` (`fd519195e96b…`) |
| Pre-registration | git tag `prereg-corpus-v1`: `corpus.yaml` committed alone, before any fetch |
| Snapshot date | `declared_fetched_on: 2026-10-21`; publication cutoff 2024-12-31 |
| Builder | `bio-claim-check corpus build`, tool version 0.0.1, sieve v2 ([ADR 0010](adr/0010-evaluation-corpus-and-split.md), [ADR 0011](adr/0011-sieve-v2-and-sealed-dataset.md)) |
| Source | PubMed/MEDLINE records via Europe PMC (citable policy: [ADR 0008](adr/0008-citable-sources-medline-abstracts.md)) |
| Licence | Our additions CC-BY-4.0; PubMed metadata under the NLM terms; code Apache-2.0 |

## 1. Purpose

To measure what a claim verifier catches when an agent overstates what an abstract says, and how often
it raises false alarms on faithful claims. The corpus supplies the abstracts (by id), the research
questions, and the **candidate** abstracts on which each kind of overstatement can be planted fairly.

It is **not** a gold standard of overstated claims. It contains no claims and no claim labels yet; only the two dev checks in §5.

## 2. Composition

**Domains.** Three drug-repurposing areas:
- `glp1-neuro`: GLP-1 receptor agonists in Alzheimer's and Parkinson's disease (dev and test).
- `metformin-onc`: metformin in oncology (dev and test).
- `statin-neuro`: statins in Alzheimer's, Parkinson's and dementia (**held out: test only**).

**Questions (27).** Each has a natural-language text, a title-anchored Europe PMC search string, a split
and an answerability flag.

| Domain | dev answerable | dev unanswerable | test answerable | test unanswerable |
|---|---|---|---|---|
| glp1-neuro | 3 | 1 | 3 | 2 |
| metformin-onc | 3 | 1 | 3 | 2 |
| statin-neuro | — | — | 6 | 3 |

Provenance: AI-drafted, AI-reviewed (consult), author-approved. Not expert-written.

**Sources.**

| Split | Sources | Clusters | Reviews | MeSH not indexed | Protocols | Retracted |
|---|---|---|---|---|---|---|
| dev | 654 | 652 | 234 | 221 | 5 | 6 |
| test | 1204 | 1200 | 422 | 393 | 6 | 6 |

Each row holds `MED:<pmid>`, the questions and ranks that retrieved it, its cluster and split,
publication types, MeSH headings (or `null` if not yet indexed), the retraction flag, `abstract_sha256`,
any never-candidate reasons, and the evidence for each candidate kind. No abstract text, titles or raw
responses are shipped (publisher copyright).

## 3. Collection

1. The spec (`corpus.yaml`) was committed and tagged before any fetch.
2. For each question: the citable records among the **first 100 Europe PMC hits** for
   `(<search>) AND FIRST_PDATE:[1900-01-01 TO 2024-12-31]`, in relevance order. No paging, no top-ups.
   Citable = MEDLINE source, a PMID, an English abstract, and not a notice, comment, editorial, letter or
   news item (ADR 0008).
3. One request per second, through a content-addressed cache. A second build in read-only mode, from
   the same cache, tool version and declared date, was **byte-identical** on the author's machine.
4. Papers that share an NCT id or a normalised title form one cluster. A cluster with any source
   retrieved by a held-out question goes to test; otherwise a public salted hash puts about half the
   clusters in dev.
5. `corpus seal` wrote `SEALED`; CI runs `dataset_problems` on every commit.

## 4. Candidates (sieve v2)

A deterministic sieve (no LLM) marks where each kind of overstatement **could** be planted fairly. For
example, a `preclinical_to_clinical` trap needs a paper whose finding is only in animals or cells.
Retracted papers, reviews, protocols and records with no publication types are never candidates; records
not yet MeSH-indexed are never candidates for the MeSH-based kinds.

| Kind | dev | test | Rule |
|---|---|---|---|
| `preclinical_to_clinical` | 103 | 187 | MeSH Animals without Humans, or cell-line MeSH without any clinical design |
| `correlation_as_causation` | 53 | 142 | Observational design MeSH or type, and no trial type |
| `nonsignificant_as_effect` | 68 | 141 | A null-result sentence that is not about baseline balance |
| `certainty_inflation` | 229 | 422 | A hedge in one of the last two sentences |
| `background_as_result` | 18 | 41 | A prior-evidence claim in the first three sentences, then a results sentence |

Every kind has at least 25 test candidates (the S07 target). Per-domain counts for every
domain × split × kind cell, zeros included, are in `manifest.json`. They are descriptive; the GLP-1
domain is small for `correlation_as_causation` (test 5) and `background_as_result` (test 3).

**Candidates are not labels.** Sieve precision on test is measured by the author's audit (below).

## 5. Checks done so far

**`background_as_result` dev pilot** (declared before the build: precision below 60 % would drop the
kind from scoring). One AI agent (single judge, the build session's coding agent; the author did not
review the items) read all 18 dev `prior_finding` candidates in full against the pre-declared criterion
"the paper's own results do not establish the background statement". **12/18 confirmed (67 %, Wilson
95 % CI 0.44–0.84)**, so the kind stays; the lower bound is below 60 %, so precision is uncertain. The
six rejections are mostly papers whose own results confirm the background effect they cite. Per-item
record: [`docs/pilots/background_as_result-dev-v1.csv`](pilots/background_as_result-dev-v1.csv). An
earlier, unrecorded tally from the same session (16/18) is withdrawn and replaced by this record.

**Dev unanswerable re-check** (against the frozen dev pools, `questions.jsonl` sha256 `81a6600b…`). The
rubric: no abstract in the question's top 10, filtered to its own split, states the compared effect,
population or quantity.

| Question | Asks for | Own-split pool | Result |
|---|---|---|---|
| glp1-q4 | semaglutide CSF/plasma ratio in Alzheimer's disease | 11 | **Holds.** No abstract in the top 10 states the ratio |
| metformin-q4 | metformin concentration in glioblastoma tissue at antidiabetic doses | 47 | **Holds.** A phase I dose study and cell/xenograft work, but no tissue concentration |

**Dev trap set (S13, [ADR 0022](adr/0022-trap-set-and-outcomes.md)).** Traps are planted only on
dev sources. Each sampled source has one model call (`gpt-6.1-sol`) that drafts a supported parent and a
trap of the sampled kind. A pure gate drops claims over 30 words, claims copying an 8-word run of the
abstract, and claims echoing a 6-word run of a rule-pack example. Each parent and each trap, including
the rule-floor swaps, is decided in one sheet. The maintainer is not a biomedical researcher, so dev-v1
will be confirmed by a two-model panel (gemini-4-argon and grok-4.7, unanimous only) and will be a
**silver standard** ([ADR 0023](adr/0023-model-panel-confirmation.md)): rows will carry `origin = model`
and `confirmed_by = model_panel`, with the votes in `traps/dev-v1.panel.json`. Until the panel has run,
no dev-v1 set exists. Keeping only rows two LLMs
agree on probably keeps easy traps, so a catch rate on dev-v1 is probably inflated. This is a **controlled paired design**: one call writes
both claims, which favours lexical contrasts, so trap catch rates are not rates on natural spin.
The draft targeted 12 traps per kind; the cohort is fixed and a kind the panel leaves short stays short. `background_as_result` is capped at its 9 eligible dev
sources (18 sieve candidates, 9 within a question's pool), so its counts are smaller and less precise.
Counts and attrition are in `docs/dev-log/S13.md`.

**Not done yet, by design:**
- **Test audit.** The author confirms the first 50 test candidates per kind in the public order, only
  after the prompts and rule packs are frozen (now `prompts-frozen-v2`, S12c). Until then nobody on the
  project reads test abstracts.
- **Test unanswerable check**, at the same time.

## 6. Known limits

- **Single rater.** Every judgement so far has one judge (the dev pilot: an AI agent; the test audit:
  the author). Labels will be called "author-confirmed" until a
  second researcher double-codes at least 20 % per kind and agreement (κ) is reported.
- **AI consult disclosure.** Before the build, an AI consult read the top-10 titles and abstracts of the
  GLP-1 and metformin **test** questions to check that the unanswerable ones were plausible. Its output
  was never used for prompt or rule tuning and stays embargoed until the prompt freeze. Statin pools
  were checked by hit counts only.
- **Pool bias.** Reviews and unindexed records stay in the pools but are never candidates, so the
  candidate set leans towards older, indexed primary research.
- **Title-anchored, relevance-ranked pools.** "Citable records among the first 100 hits" depends on
  Europe PMC's ranking on the snapshot date; it is not a systematic search.
- **Planted vs natural errors.** Traps are planted by a model in a paired design (ADR 0022); natural
  overstatement may look different. The two are reported separately.
- **Faithfulness is not truth.** A claim faithful to a 2023 abstract can be wrong today; the 2024 cutoff
  misses later null results.
- **The MeSH-cue baseline shares the sieve's signal.** Paired catch-rate vs false-alarm comparisons
  mostly cancel this; the baseline's raw catch rate alone overstates it.
- **Sieve v2 regex limits (known, kept for the frozen v2).** The null-result p-value pattern misses
  a p value of 1 (`p = 1.0`); the `prior_finding` results cue accepts a
  bare `p =` without a number. Fixing either changes candidates, so it needs sieve v3 and a new ADR.
- **English only.** The quote check and the sieve are validated in English.
- **Reproducibility.** Byte-identical rebuilds hold only on the author's machine, because the response
  cache is not redistributed. Others get the PMIDs, query strings, pool and response hashes and
  `abstract_sha256`; `hydrate` (later) will report drift.
- **Snapshot.** Retraction status and MeSH indexing are as of the fetch date and are not kept current.

## 7. Credit

Records courtesy of the U.S. National Library of Medicine. NLM does not endorse this dataset. Retrieved
through Europe PMC.
