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
- **Challenge set:** `challenge/dev-v1.jsonl`, 16 curated dev (claim, source) items with expected labels.
  It is a regression and sanity check of the verifier, not an accuracy estimate (ADR 0020).
- **Judge fingerprint (`judge_sha256`):** the sha256 over the bytes of the files that decide a verdict
  (prompts and their rendering, provider codecs, the retry loop, rule pack, quote location, negation,
  disposition), the `rapidfuzz` version and both model
  specs. Any edit, even to a docstring, makes a new judge.
- **Prompt freeze:** `freeze/<name>.json`, which binds one judge fingerprint to the committed challenge
  result. `app/freeze.py` pins its bytes and names the active one (v2, ADR 0021). A test-split audit records the active
  `freeze_sha256` as its `prompts_sha256`. A dev audit's `prompts_sha256` is typed by the author.
- **Trap set:** `traps/dev-v1.jsonl`, confirmed dev items with predeclared expected outcomes; dev-v1 is
  confirmed by a model panel, so it is a silver standard ([ADR 0023](./adr/0023-model-panel-confirmation.md))
  ([ADR 0022](./adr/0022-trap-set-and-outcomes.md)). Each source gives a **parent** (a supported claim),
  a **model trap** (the parent rewritten to commit one kind) and up to three **rule-floor traps** (a
  direction, operator or dose swap of the parent). Claims only, never abstract text.
- **Pair table / discriminated:** for one (kind, generator), every trap's disposition against its own
  parent's. A pair is **discriminated** when the trap is flagged and its parent passed
  ([ADR 0024](./adr/0024-proof-checkpoint-go-adjust.md)). Shared parents make these descriptive counts.
- **Go/adjust verdict:** the proof checkpoint's predeclared rule on dev-v1 (policy `adr-0024-v1`); it
  changes how the demo frames the verifier, never whether counts are shown, and never tunes the judge.
- **Caught / exact / false alarm:** a trap is *caught* when its disposition is `flagged`, and *exact* when
  its label (and reason, if declared) is also the expected one. A *false alarm* is a flagged parent.
  `needs_review` and `failed` stay in every denominator. All are exploratory on dev.
- **Model panel:** two or more LLM raters of distinct model families, none the trap writer's or the
  verifier's, that each fill one audit sheet under a committed protocol. Only a unanimous row is kept.
- **Panel ledger:** `traps/<set>.panel.json`, the committed record of each rater's vote on each candidate,
  with the draft, protocol and sheet hashes. No reasons and no claim text; CI recomputes the set from it.
- **Rater:** a registered panel member (`app.models.RATER_FAMILIES`); its family comes from the registry,
  never from the command line.
- **Silver standard:** labels confirmed by a model panel, not by a domain expert. Never called ground
  truth or expert-labelled; a catch rate on it is conditional on the panel's agreement.
- **Trap draft:** `var/traps/dev-draft-*.jsonl`, every row a run produced, including writer failures and
  gate exclusions. It is never committed. The audit sheet is bound to its sha256.
- **Writer family flag:** `writer_family_flag` in a trap result is true when the trap writer and the
  verifier share a model family, which is a disclosed bias.
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
- **Run record:** what an attempt leaves under the var root ([ADR 0018](./adr/0018-run-record.md)):
  always one ledger row and (unless it cannot be opened) a trace; on success also a canonical artifact
  and manifest.
- **Manifest:** `runs/<run_id>/manifest.json`, published last. It records what produced the artifact
  (command, inputs, models, prompt hashes, package version, artifact hash) and no time, path or cache
  mode. A run folder without it is incomplete.
- **Run id:** the first 16 hex characters of the manifest's sha256. It changes with the package version.
- **Trace:** `events/<UTC start>-<n>.jsonl`, the attempt's pipeline events, one per line. It holds times
  and cache hits, so it is never compared byte for byte.
- **Ledger:** `ledger.jsonl`, append-only, one row per attempt: status, code, run id (on success only),
  trace name, cache mode and usage per model. It is the run's money record.
- **Unmeasured attempt:** an attempt that may have reached the provider but reported no usage (a failed
  call, or a start with no end). Counted apart, never as 0 tokens.
- **Model family:** who trained a deployment (`openai`, `anthropic`, `moonshot`, and the panel raters'
  `google`, `xai`), apart from the
  provider that serves it. A live report flags `same_family` when the answerer and the verifier share
  one, since they may share blind spots ([ADR 0019](./adr/0019-llm-verifier-and-live-run.md)).
- **Live notice:** the notice on a live report: each claim, if any, was checked by an LLM verifier
  against the retrieved abstracts it cites, and the labels are model judgements, not expert review.
- **Declared LLM:** a role's agent, provider, deployment, model version and prompt hash, recorded in the
  manifest from the wiring, so the run id names a prompt even if no call of that role finished.
- **Dev run:** `run --dev QUESTION_ID`: the live flow over the sealed dev pool of one dev question, for
  tuning only. Its artifact also counts the dropped sources by reason; it is never re-checked or reported.
- **Retraction re-check:** `retractions RUN_ID` asks Europe PMC again, uncached, whether each paper a live
  run cited is retracted now, beside its status in the run. It writes `var/retractions/…` and never
  changes the run.
- **`run.cancelled` / `run.internal`:** ledger codes for an interrupted attempt and for an unexpected
  exception (a bug). They are run codes, not error classes, so they are not in `error-codes.md`.

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
