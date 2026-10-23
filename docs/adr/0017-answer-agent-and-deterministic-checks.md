# ADR 0017 — Answer agents, abstention, and checks code can make without a model

- **Status:** Accepted
- **Date:** 2026-10-23
- **Supersedes / Extends:** Amends 0006 (negation is always derived, by one versioned detector) and invariants
  I19/I20 (the fake demo may show `passed`; reports carry no notes); extends 0015 (the first feature agents)
- **Related:** 0003, 0005, 0010, 0011, 0012
- **Enforced by:** `tests/unit/common/test_negation.py` · `tests/unit/contracts/test_verdict.py::test_a_verdict_made_under_other_negation_rules_is_rejected` · `tests/unit/features/test_answer_models.py` · `tests/unit/features/test_llm_answerer.py` · `tests/unit/features/test_answer_prompts.py::test_identifiers_are_locked` · `tests/unit/features/test_self_containment.py` · `tests/unit/features/test_dev_pool.py` · `tests/unit/app/test_answer_dev.py` · `tests/contract/test_answerer_contract.py` · `tests/contract/test_llm_agent_contract.py`

## Context

Until S10 every answer was scripted and the negation check was `not_run`, so no pair could be `passed`.
The first real answerer brings three risks this project exists to measure, not hide:

- **Citation defects laundered by a repair.** The runner's one repair turn (ADR 0012) would let a model
  "fix" a malformed or duplicate cite after being told it was wrong, so the stored answer would look cleaner
  than what the model produced.
- **Claims that lean on context the verifier never sees** ("this drug", "the same trial"). A verifier given
  one claim and one abstract cannot check what such a claim refers to.
- **A located quote from a negated sentence** ("did not reduce decline") scored as support.

## Decision

1. **Two modes, two agents, two prompts.** `StrictAnswerLlmAgent` and `OverEagerAnswerLlmAgent` subclass
   `BaseLlmAgent[AnswerPayload, AnswerOutput]` directly. Each has its own prompt constant (its own hash)
   that states what the mode does **not** do. A test locks names, versions and placeholders; any change
   bumps the version and is tuned on dev questions only.
2. **Abstention is an empty claim list.** Only Strict is told to abstain; an empty Over-eager answer is
   accepted and shown as such, never refused or retried (we measure the mode). There is no reason field.
3. **The output model carries structure only** (`{claims: [{text, cites}]}`, strict-schema compatible, no
   semantic validators), so the repair turn can only fix JSON shape. Code converts it with `to_claims`:
   ids `c1…cn` are assigned by code; a blank claim, a claim with no cites, a duplicate cite or a malformed
   id raises `answer.invalid_claims` (counts per defect, no text) and is **never repaired**. A well-formed
   id that was not retrieved is kept and reported as an invented citation.
4. **Self-containment is flagged, not rewritten.** `dangling_claims` (pure, claim-level) adds a
   `dangling_reference` finding (no `source_id`) after the invented-citation findings. A rewrite would
   change meaning and lose the original; it waits for an audit trail (backlog). Findings are **not** folded
   into the dispositions: `passed` (ADR 0006) covers the (claim, source) checks only, so a claim can be
   `passed` and carry a `dangling_reference`. `run` therefore always prints finding counts beside the
   disposition counts.
5. **Negation is one conservative, versioned detector.** `common/negation.py::is_negated`: any cue in the
   sentence(s) holding the located span gives `NEGATED`; only "not only" is exempt. A dot after a listed
   abbreviation ("Fig.", "et al.", "vs.") does not end a sentence. `NEGATION_RULES = 2` is stored in every
   `Verdict`; a verdict made under another version is rejected by `verify_against`, which `Report` runs on
   load, never silently re-scored. A false `NEGATED` costs a `needs_review`; a false `CLEAR` would cost a wrong `passed`. A
   correctly supported null result also goes to `needs_review`; that is accepted.
6. **Dev answers come from the sealed dev pool only.** `answer dev` checks the seal first, refuses unknown
   and test questions before any fetch, re-sends the recorded query, and passes only that question's dev
   sources whose abstract hash still matches, in recorded rank order. Every drop is counted by reason,
   including expected sources that did not come back and usable ones ranked below `k`. An empty pool
   fails; a short pool warns.
7. **Replay is never shown as spend.** Usage is split into live calls (with tokens), cache hits
   (without) and failed calls (counted, usage unknown); unreported reasoning tokens are counted as
   unreported, never as 0; money is "unpriced" while prices are `None`.

## Consequences

- **Positive:** a pair can now be `passed`, but only when the evidence sentence has no negation. Every
  citation defect is either refused loudly or reported; none is repaired away. Prompt tuning cannot see a
  test-split source.
- **Negative / costs:** reports written before S10 do not load (they lack `negation_rules`); only fake
  reports existed. The conservative detector sends correctly supported null results to `needs_review`;
  its precision is unmeasured until labels exist. Over-eager on `gpt-6.1-sol` hedges more than intended
  (dev-log S10); the mode is kept as designed, and traps (S13) do not depend on it.
- **Follow-ups:** the P2 rewrite with an audit trail; negation precision on labelled data (both backlog).
