# Glossary

The words this project counts with. Each table below lists the exact values of one enum in
`bio_claim_check.features.contracts.labels`; a test fails if a table and its enum drift apart. Meaning and
counting rules are in [ADR 0006](./adr/0006-two-axis-verdict-and-disposition.md).

## Terms

- **Claim:** one self-contained statement in an agent's answer, citing one or more sources.
- **Pair:** one (claim, cited source). The unit every verdict and every metric is computed on.
- **Verdict:** the system's conclusion for one pair: the model's label plus what code verified.
- **Rule pack:** a YAML file describing ways claims overstate their sources, with examples.
- **Author-written / reviewed:** a rule-pack example is author-written until a named person other than
  the author reviews it. Neither is called expert-labelled unless the reviewers are independent experts.

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
| `not_run` | No negation check has run on this pair (the detector arrives in S10) |
| `clear` | The located quote is not under a negation |
| `negated` | The located quote sits under a negation, e.g. "no significant reduction" |

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
