# bio-claim-check evaluation corpus

A frozen, sealed set of PubMed records for measuring what a claim verifier catches. The full data card
is [`docs/data-card.md`](../docs/data-card.md); the design decisions are in
[ADR 0010](../docs/adr/0010-evaluation-corpus-and-split.md).

## What is shipped

| File | Contents |
|---|---|
| `corpus.yaml` | The pre-registered spec: questions, Europe PMC search strings, cutoff, salts, trap kinds, sieve version. Committed alone before any fetch (tag `prereg-corpus-v1`) |
| `questions.jsonl` | One row per question: the exact query sent, the pool size, the pool size in the question's own split, and sha256 hashes of the ranked pool and of the raw API response |
| `dev/sources.jsonl`, `test/sources.jsonl` | One row per source: `MED:<pmid>`, the questions and ranks that retrieved it, cluster id, split, publication types, MeSH headings, retraction flag, `abstract_sha256`, never-candidate reasons and candidate evidence (rule name, MeSH terms or a sentence offset) |
| `manifest.json` | sha256 of the spec and every data file, candidate counts per domain × split × kind, the declared fetch date, the tool version and the NLM notice |
| `SEALED` | sha256 of `manifest.json`, which hashes `corpus.yaml`, `questions.jsonl`, `dev/sources.jsonl` and `test/sources.jsonl`. Any edit to these files or the manifest breaks it, and CI fails. This `README.md` is not sealed |

## What is not shipped

- **No abstract text, titles or raw API responses.** Abstracts carry publisher copyright. Offsets refer
  to the cleaned abstract (`clean_abstract`), and `abstract_sha256` lets you check that the text you
  fetch is the text the offsets refer to.
- **No claim labels yet.** Candidates are sieve output, not confirmed overstatement opportunities. The test
  audit happens after the prompt freeze (ADR 0010).

## Use

```bash
uv run bio-claim-check corpus verify     # exit 0 if every hash, split and count checks out
```

`hydrate` (re-fetching the text and reporting drift by hash) arrives in a later release. This README is
not part of the sealed bytes.

## Credit and terms

- Records courtesy of the U.S. National Library of Medicine (PubMed/MEDLINE), retrieved through
  [Europe PMC](https://europepmc.org). NLM does not endorse this dataset or this tool.
- The metadata are a dated snapshot (`declared_fetched_on` in `manifest.json`) and are **not kept
  current**. Retraction status and MeSH indexing may have changed since; check PubMed before relying on
  any single record.
- Our additions (the spec, splits, clusters, candidate evidence, offsets and hashes) are released under
  CC-BY-4.0. The PubMed metadata (PMIDs, publication types, MeSH headings) remain under the
  [NLM terms](https://www.nlm.nih.gov/databases/download/terms_and_conditions.html). The code is
  Apache-2.0.
