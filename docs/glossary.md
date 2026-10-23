# Glossary

The words this project counts with. Each table below lists the exact values of one enum (`labels` and
`finding` and `corpus` in `bio_claim_check.features.contracts`, `CacheMode` in `bio_claim_check.engine.cache`, `Provider`, `FinishReason` and `LlmFailureKind` in `bio_claim_check.engine.llm`); a test
fails if a table and its enum drift apart. Meaning and
counting rules are in [ADR 0006](./adr/0006-two-axis-verdict-and-disposition.md).

## Terms

- **Claim:** one self-contained statement in an agent's answer, citing one or more sources.
- **Pair:** one (claim, cited source). The unit every verdict and every metric is computed on.
- **Verdict:** the system's conclusion for one pair: the model's label plus what code verified.
- **Rule pack:** a YAML file describing ways claims overstate their sources, with examples.
- **Author-written / reviewed:** a rule-pack example is author-written until a named person other than
  the author reviews it. Neither is called expert-labelled unless the reviewers are independent experts.
- **Citation not retrieved:** a claim cites a source that retrieval never returned. That pair is
  `flagged` without calling the verifier, and the check records an `invented_citation` finding.
- **Finding:** what a deterministic check (no LLM) found in an answer, independent of any verdict.
- **Citable paper:** a MEDLINE record (`MED:<pmid>`) with a title, an abstract in English and no excluded
  publication type (retraction notice, erratum, comment, editorial, letter, news). Only these are
  retrieved ([ADR 0008](./adr/0008-citable-sources-medline-abstracts.md)). Reviews are citable.
- **Retracted:** the paper is flagged as retracted by Europe PMC (a `Retracted Publication` type or a
  `Retraction in` notice). Retracted papers are kept and marked, never dropped. The flag is as of the
  first fetch, because cached responses are snapshots ([ADR 0009](./adr/0009-cache-and-replay.md)).
- **Sieve:** the deterministic eligibility rules (no LLM) that mark a source as a *candidate* for a trap
  kind, from its MeSH headings, publication types or sentences ([ADR 0010](./adr/0010-evaluation-corpus-and-split.md)).
  `SIEVE_VERSION` names the rule set.
- **Candidate:** a source the sieve marks as eligible for one trap kind, with the evidence it used. In the
  test split, a candidate counts only after the author confirms it in the audit.
- **Cluster:** sources joined by a shared trial registry id (`NCT…`) or the same normalised title. A
  cluster is never split across dev and test; its id is its smallest source id, compared numerically.
- **Seal:** `datasets/SEALED` holds the sha256 of `manifest.json`, which hashes every data file and the
  spec as written. Any later edit to the dataset breaks the seal; `corpus verify` and CI check it.
- **Audit:** the author's review of the first `audit_n` candidates of one kind in one split, in a public
  hash order. Each decision is `confirm` or `reject` (with a reason). The record is bound to the seal and
  the prompts hash, and its precision is labelled "author-confirmed, single rater".
- **Prior finding:** the sieve rule for `background_as_result`: an early sentence reports prior evidence
  with an effect verb, and a later sentence reports this study's results.
- **Split:** `dev` (for tuning prompts and rule packs) or `test` (sealed, for reported numbers only).
- **Repeat:** one of several identical model requests made on purpose to measure instability. Its
  `repeat_idx` is part of the cache key, so repeats are distinct provider calls and replay keeps them
  apart ([ADR 0012](./adr/0012-llm-engine-runner-and-cost.md)).
- **Usage:** the token counts the provider reported for one call (input, output, reasoning, cached
  input). Never estimated. Reasoning tokens are part of output tokens; cached input is part of input.
- **Spend:** what a run actually paid: live calls, replayed calls (cache hits), the usage of the live
  calls and their cost. A cache hit adds no cost.
- **Unpriced:** a model has no price on record, so the cost is unknown (`None`), never shown as 0.
  Prices are entered by hand, with the date and the page they came from.
- **Served model:** the model name the provider reports in its reply (`LlmResponse.served_model`).
  Provenance only: it is not in the cache key; the pinned `model_version` is.
- **Forced tool use:** how Claude returns structured output here: one tool whose input schema is the
  output schema, and `tool_choice` naming it. Its input becomes the reply text. Thinking is off
  ([ADR 0014](./adr/0014-provider-adapters-and-pinned-models.md)).
- **Structured-output matrix:** the table in ADR 0014 of how each deployment returns structured output
  and whether that was probed live.
- **Recorded / synthetic fixture:** a recorded fixture is a scrubbed live exchange with fictional text; a
  synthetic one is built by hand from the documented shape, for states that cannot be provoked honestly
  (filters, refusals, throttling). Every fixture says which it is.
- **Agent:** a subclass of `BaseLlmAgent`: a name, a prompt, an output model and one `variables` method.
  It runs through the one `LlmRunner` ([ADR 0015](./adr/0015-llm-agent-base.md)).
- **Pipeline event:** a typed, timestamped record of what a run did (a stage started, an LLM attempt
  finished with its usage, a retry was scheduled). It carries ids, counts and codes, never text, and is
  never part of a canonical artifact ([ADR 0016](./adr/0016-pipeline-events-and-clock.md)).
- **Fake run:** `run --fake` uses fictional papers (`FAKE:` ids) and scripted answers and verdicts. Its
  report says so in `provenance` and `notice`; it is a demo of the pipeline, never a result.

## AnswerMode

How the answering agent is instructed. Both exist so the verifier can be measured on careful and careless answers.

| Value | Meaning |
|---|---|
| `strict` | Answer only what the abstracts state, with their caveats; abstain when they do not answer the question |
| `over_eager` | Answer confidently and drop caveats, the way a careless agent does |

## Label

What the verifier model judged.

| Value | Meaning |
|---|---|
| `supported` | The source says what the claim says, at the same strength |
| `overstated` | The source supports a weaker or narrower statement; a reason is required |
| `contradicted` | The source says the opposite, or its result rules the claim out |
| `not_in_source` | The source does not address the claim |

## EvidenceStatus

What code found when it looked for the model's quoted evidence in the cleaned abstract.

| Value | Meaning |
|---|---|
| `located` | The quote's tokens appear exactly, in order, in the abstract (ADR 0005) |
| `near` | Not located, but a close match exists; routed to review, never counted as found |
| `absent` | No exact or close match: the quote is not in the source |
| `not_required` | No quote, because the label is `not_in_source` |

## NegationCheck

| Value | Meaning |
|---|---|
| `not_run` | No evidence was located, so there is no span to check |
| `clear` | No negation cue anywhere in the sentence(s) holding the located quote |
| `negated` | A negation cue occurs in the sentence holding the quote, before, inside or after it, e.g. "no significant reduction". Conservative on purpose (ADR 0017) |

## Disposition

What a reader should do with a pair. Derived by code, never produced by a model.

| Value | Meaning |
|---|---|
| `passed` | Every check passed. It does not mean the claim is true |
| `needs_review` | A person should look: near-match evidence, a negation, or a check that has not run |
| `failed` | The verifier produced no usable output; counted, never dropped |
| `flagged` | The claim misrepresents its source, or its evidence is not in the source |

## FailureKind

| Value | Meaning |
|---|---|
| `structured_output` | The model's output did not validate, even after one repair |
| `content_filtered` | A provider content filter blocked the request or the response |
| `provider_error` | The provider failed after retries |

## OverstatedReason

How an `overstated` claim goes beyond its source.

| Value | Meaning |
|---|---|
| `preclinical_to_clinical` | An animal or cell result is stated as an effect in people |
| `background_as_result` | Background or prior work in the abstract is cited as this study's finding |
| `surrogate_as_clinical` | A biomarker or surrogate change is stated as a clinical benefit |
| `correlation_as_causation` | An observational association is stated as cause and effect |
| `selective_analysis_as_main` | A subgroup, secondary or post-hoc result is stated as the main result |
| `nonsignificant_as_effect` | A non-significant result is stated as an effect or as proof of no difference |
| `dose_or_exposure_extrapolation` | A result is extended to doses, durations or exposures that were not studied |
| `population_extrapolation` | A result is extended to a population that was not studied |
| `certainty_inflation` | Hedged or preliminary findings are stated as established |
| `other` | None of the above; the verifier must explain in its reason |

## FindingKind

| Value | Meaning |
|---|---|
| `invented_citation` | A claim cites a source that was not among the retrieved papers |
| `dangling_reference` | A claim refers to something outside itself ("This drug …", "as noted above"), so the verifier cannot know what it is about. Flagged only; the claim is still verified |

## CacheMode

How retrieval (and, from S08, model calls) use the local cache (`BCC_CACHE_MODE`, ADR 0009).

| Value | Meaning |
|---|---|
| `read-write` | Serve a stored response; on a miss, fetch, validate and store it (first write wins) |
| `read-only` | Serve a stored response; on a miss, stop with an error and never fetch (replay) |
| `off` | Always fetch; never read or write the cache |

## CorpusSplit

Which half of the evaluation corpus a source or question belongs to (ADR 0010).

| Value | Meaning |
|---|---|
| `dev` | Used to tune prompts and rule packs; never reported as a result |
| `test` | Sealed before any tuning; the only split behind reported numbers. The held-out domain is all test |

## NeverReason

Why a source can never be a trap candidate. The source stays in the pool, so retrieval stays realistic.

| Value | Meaning |
|---|---|
| `retracted` | The paper is retracted |
| `review` | A review, systematic review or meta-analysis: it reports others' findings |
| `unknown_publication_types` | No publication type is recorded, so the sieve cannot prove what the study is |
| `mesh_not_indexed` | No MeSH headings yet; only the MeSH-based kinds are blocked |
| `protocol` | A trial protocol: it has no results to overstate |

## Provider

Who serves a model deployment (ADR 0012). Each needs its own settings (`BCC_FOUNDRY__*`, `BCC_ANTHROPIC__*`,
`BCC_OLLAMA__*`) unless the run is a read-only replay.

| Value | Meaning |
|---|---|
| `foundry_openai` | A model on Azure AI Foundry, called through its OpenAI-compatible endpoint |
| `foundry_anthropic` | A Claude model on Azure AI Foundry, called through the Anthropic SDK |
| `anthropic` | A Claude model called through the Anthropic API directly |
| `ollama` | A local model, pinned by digest |

## FinishReason

Why the provider stopped generating, normalised across providers.

| Value | Meaning |
|---|---|
| `stop` | The model finished its reply |
| `length` | The reply hit the output-token limit and is truncated; never repaired |
| `content_filter` | A provider content filter blocked the reply; never repaired, always counted |

## LlmFailureKind

Why a structured model call produced no usable output. S12 maps each kind to a `FailureKind`.

| Value | Meaning |
|---|---|
| `invalid_output` | The reply did not validate against the schema, even after one repair |
| `truncated` | The reply hit the output-token limit |
| `content_filtered` | A provider content filter blocked the request or the reply |
