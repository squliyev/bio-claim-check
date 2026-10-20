# ADR 0006 — Two-axis verdict, one disposition, and the overstatement taxonomy

- **Status:** Accepted
- **Date:** 2026-10-22
- **Supersedes / Extends:** Extends 0003 and 0005
- **Related:** 0003, 0005
- **Enforced by:** `tests/unit/contracts/test_verdict.py::test_every_cell_is_table_or_impossible`, `tests/unit/contracts/test_verdict.py::test_table_matches_adr_0006`, `tests/unit/contracts/test_claim_disposition.py::test_claim_disposition_worst_case`, `tests/unit/app/test_run_usecase.py::test_non_retrieved_cites_never_reach_the_verifier`, `tests/unit/contracts/test_verdict.py::test_verify_against_rejects_forged_spans`, `tests/unit/contracts/test_verdict.py::test_a_stored_negation_result_must_be_reproduced`, `tests/arch/test_guards.py::test_no_verdict_is_constructed_outside_its_home`, `tests/unit/contracts/test_verifier_output.py::test_the_llm_facing_schema_is_strict_mode_compatible`, `tests/arch/test_schemas.py::test_committed_schemas_are_fresh`, `tests/arch/test_project_files.py::test_glossary_matches_the_enums`.

## Context

Every number this project reports is a count of verdicts. If one field mixed what the model *judged* with
what code *verified*, a model that paraphrases its evidence would be scored as if it had quoted it, and a
model that flags everything would look like a good detector. These definitions are pre-registered later
(S15), so they must be total, unambiguous and fail closed.

## Decision

1. **Two axes, never merged.**
   - `Label` is the model's judgement: `supported`, `overstated`, `contradicted`, `not_in_source`.
     `contradicted` (the source says the opposite) replaced the earlier `unsupported`, which overlapped
     with "the source is silent" (`not_in_source`).
   - `EvidenceStatus` is what code found when it looked for the quote (ADR 0005): `located`, `near`,
     `absent`, `not_required`. `NegationCheck` records whether a located quote sits under a negation:
     `not_run` until the detector exists (S10), then `clear` or `negated`.
2. **One derived `Disposition`** per (claim, source) pair, from a total table over 4 × 4 × 3 cells. The 16
   possible cells map as follows; the other 32 are impossible and are rejected at construction.

   | Label | Evidence | Negation | Disposition |
   |---|---|---|---|
   | supported | located | clear | `passed` |
   | supported | located | negated or not_run | `needs_review` |
   | supported | near | not_run | `needs_review` |
   | supported | absent | not_run | `flagged` (quote not in the source) |
   | overstated / contradicted | located | any | `flagged` |
   | overstated / contradicted | near / absent | not_run | `flagged` |
   | not_in_source | not_required | not_run | `flagged` |

   - `passed` means *every check passed*. It does not mean the claim is true.
   - Until the negation detector exists, no pair can be `passed`. That is deliberate: the label would
     otherwise promise a check that never ran.
   - `failed` comes only from a `VerifierFailure` (structured-output error, content filter, provider
     error). It is counted, never dropped, so failures cannot shrink a denominator.
3. **The pair is the unit of analysis** (as in SciFact-style evaluation). A claim's disposition is the
   **worst** of its pairs: `flagged` > `failed` > `needs_review` > `passed`. Every cited source must have
   exactly one outcome; a missing, extra or misfiled outcome raises.
   - **Extended in S05:** an outcome is a `Verdict`, a `VerifierFailure` or a `CitationNotRetrieved`.
     A cited source that retrieval never returned is `flagged` without calling the verifier: judging a
     claim against nothing is meaningless, and `failed` would hide a fabricated citation as a pipeline
     error.
4. **One trusted path to a verdict.** `Verdict.finalise` computes the evidence status and span with
   `locate_quote`/`near_match`, and the negation result by running a negation detector on the located
   span (no detector → `not_run`); it never accepts a stored negation value. Outside
   `contracts/verdict.py`, code may only call `finalise` or `model_validate` (for replay). Replay and
   benchmarking call `Verdict.verify_against(abstract, detector)`, which recomputes the status, span and
   negation result and rejects any that do not match; a stored `clear`/`negated` cannot be accepted
   without the detector. `model_copy(update=...)` is refused, because pydantic skips validation there.
   Python cannot make a model truly unforgeable (`BaseModel.model_copy` still bypasses the override, so
   `claim_disposition` re-checks a claim's citations); this is the integrity check, and the construction
   guard is a backstop.
5. **The LLM-facing schema is a flat object**, not a union by label. OpenAI strict mode and Claude tool
   input both need an object root with every property required. Per-label rules (a reason iff
   `overstated`; evidence iff not `not_in_source`; no blank strings) are pydantic validators whose
   messages name the field, so a repair prompt can quote them. The schema is committed in `schemas/` and
   checked against the strict subset.
6. **Overstatement reasons.** Nine reasons plus `other`. Each is linked to the literature it is drawn
   from; the mapping is the author's reading and is re-verified in the related-work review (S15).

   | Reason | Related literature |
   |---|---|
   | `preclinical_to_clinical` | Inference to humans from animal or cell research (Sumner 2014) |
   | `background_as_result` | Citation distortion (Greenberg 2009). An attribution error, not spin |
   | `surrogate_as_clinical` | Surrogate end points (Fleming & DeMets 1996) |
   | `correlation_as_causation` | Causal claims from correlational designs (Sumner 2014) |
   | `selective_analysis_as_main` | Focus on secondary, subgroup or within-group results (Boutron 2010) |
   | `nonsignificant_as_effect` | Claiming benefit or equivalence despite a non-significant primary outcome (Boutron 2010) |
   | `dose_or_exposure_extrapolation` | Inappropriate extrapolation beyond the studied intervention (Yavchitz 2016) |
   | `population_extrapolation` | Inappropriate extrapolation to other populations (Yavchitz 2016) |
   | `certainty_inflation` | Hedges removed or strengthened (Hyland 1998; Sumner 2014) |
   | `other` | Free-text reason required; never a trap kind |

   Trap kinds (S07) are a subset of these reasons, chosen by eligibility, not all nine.
7. **Rule packs** are YAML validated into frozen models. Every reason except `other` has at least one
   rule; examples are author-written until someone else reviews them (`reviewed_by`), and are never
   described as expert-labelled. The loader rejects duplicate keys, anchors, aliases, merge keys and
   non-string, non-number scalars.

## Consequences

- **Positive:** a lazy verifier cannot score well by paraphrasing or by flagging everything; failures stay
  visible; the vocabulary is frozen by committed schemas and a glossary parity test.
- **Negative / costs:** `needs_review` dominates supported pairs until S10; a flat schema needs one repair
  round for per-label errors.
- **Follow-ups:** negation detector (S10); the binary *supported vs not* primary endpoint and a cluster
  bootstrap over connected claim–source components (S15/S16); contamination checks between rule-pack
  examples and traps (S13).
