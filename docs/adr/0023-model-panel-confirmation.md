# ADR 0023 — Model-panel confirmation of the dev trap set (a silver standard)

- **Status:** Accepted
- **Date:** 2026-10-25
- **Supersedes / Extends:** amends [ADR 0022](./0022-trap-set-and-outcomes.md) decisions 4 and 8 (who
  confirms a trap set)
- **Related:** [ADR 0008](./0008-citable-sources-medline-abstracts.md), [ADR 0019](./0019-llm-verifier-and-live-run.md)
  (model families), [ADR 0020](./0020-challenge-set-and-judge-freeze.md)
- **Enforced by:** `tests/arch/test_trap_set.py::test_every_committed_trap_set_attests_who_confirmed_it` ·
  `tests/arch/test_trap_set.py::test_every_committed_trap_result_attests_its_set_dataset_and_freeze` (I79) ·
  `tests/unit/app/test_traps_usecase.py` (panel cases) · `tests/unit/features/test_traps_panel.py` ·
  `tests/unit/app/test_cli_traps.py::test_a_model_panel_writes_the_set_its_ledger_and_the_agreement`

## Context

ADR 0022 assumed that a domain-expert author would confirm all 177 candidate rows of the dev trap draft
(78 parents, 78 model traps, 21 rule-floor traps). The maintainer is not a biomedical researcher. Writing
`confirmed_by = author` would therefore be false, and AGENTS.md forbids describing such labels as expert
labels. The proof checkpoint still needs labelled traps before the hackathon, and no external expert is
available in time.

An LLM panel can confirm rows, but it brings four risks:

1. Its labels are not ground truth.
2. Keeping only rows that LLMs agree on keeps rows that LLMs find easy.
3. A rater from the verifier's or the writer's model family may share their blind spots.
4. A protocol, rater list or cohort chosen after seeing the votes could be tuned to a result.

An earlier advisory pass by one model (gemini-4-argon) read the same sheet. It had also read the verifier
prompt, so it is contaminated and is discarded (decision 7).

## Decision

1. **A two-model panel confirms dev-v1, which is a silver standard.** Items carry
   `confirmed_by = "model_panel"`. "Ground truth" and unqualified catch rates are reserved for a set that
   an external expert confirms (dev-v2, backlog). Every report of a dev-v1 outcome says "silver standard".
2. **Unanimity.** A row is kept only if every rater confirmed it, and a trap only if its parent was
   unanimous too. Any disagreement drops the row. There is no adjudication.
3. **Fixed cohort.** The 177 candidates of `var/traps/dev-draft-20-b222f76d60fb.jsonl` are the whole dev-v1
   cohort. Nothing is topped up or replaced after the panel. A kind left short is reported as short.
4. **Selection bias is predeclared.** Unanimous LLM retention probably keeps traps that LLMs find easy, so
   it probably **inflates** the verifier's catch rate. The metric is "the catch rate on unanimously
   panel-confirmed planted traps". It is never compared with an unfiltered or a naturalistic set.
5. **Reporting is predeclared.**
   - Model traps are the primary metric. Rule-floor traps are reported separately.
   - Every report gives numerators and denominators by generator and kind, parent false alarms,
     `needs_review`, `failed`, and the panel attrition (candidates → per rater → unanimous → pair kept).
   - A pooled number is secondary and labelled as a mixture.
   - Agreement is reported as raw 2x2 vote tables per role and generator (every cell, zeros included) and
     percent agreement, printed by `apply-audit` from committed code. There is no kappa: with a filtered,
     imbalanced cohort it would mislead.
6. **Raters and declared family separation (I79).**
   - The raters are gemini-4-argon (Google) and grok-4.7 (xAI), at high reasoning effort. They run as
     independent coding-agent subagents, because the app has no client for either family.
   - `app.models.RATER_FAMILIES` is a closed registry. The CLI takes a rater id only; a family is never
     typed in. An unknown id is refused.
   - Raters must be at least two, distinct, and of distinct families. None may share the family of the
     trap writer (`origin_id`) or of the verifier of the intended freeze.
   - Each result is checked against **its own** verifier: no rater may share that verifier's family. A
     later freeze therefore never invalidates dev-v1 retroactively, and a verifier from a rater's family
     is refused before any fetch.
   - This is conflict control, not statistical independence. LLMs share training data and notions of
     what is obvious.
7. **The protocol is committed and hashed.** `docs/protocols/trap-panel-v1.md` is given to each rater
   verbatim, and its sha256 is in the ledger. It must not change once the panel has run; a new protocol is
   a new file and a new set.
   - **Isolation.** Each rater works in its own `var/panel/<rater>/` holding only the protocol and its copy
     of the blank sheet. It may use only the abstract, the claim and the protocol's definitions. No web,
     PubMed or full text; no repo code, verifier prompt, outcomes, earlier advisory or other rater's sheet.
     This isolation is **instructed, not technically enforced**, and that is disclosed.
   - **Two stages.** First the claim's support is judged from the abstract alone; role, kind and generator
     are not evidence. Then the role's rule applies: a parent must be fully supported and not a close
     paraphrase of one sentence; a model trap must be unsupported in exactly its kind, with no other
     material error and no flat contradiction; a rule-floor trap must change a result the abstract states.
   - **Not blind.** Each rater sees the row's role, kind and generator, so the panel confirms intended
     labels rather than labelling blind. Stage 1 is instructed, not enforced. A blinded first pass needs a
     second sheet format (backlog C7).
   - **Generic, not tuned to this cohort.** The kind definitions are the rule pack's, verbatim, the same
     ones the trap writer was given (a parity test checks this), and the rules are generic. A first draft
     added clarifications drawn from the discarded advisory on this same sheet; they were removed before
     any rater ran (S13 implementation review #10), because they would tune the filter to this cohort's
     known failures. The person who wrote the protocol had still seen the advisory; this is disclosed.
8. **The ledger is committed and attested.** `traps/<set>.panel.json` holds the set, draft and protocol
   hashes, the intended freeze, the rater ids, each sheet's sha256, and each candidate's votes in rater
   order. It holds **no reasons and no claim text**, since reasons may quote abstracts (ADR 0008). CI
   recomputes from it that the set is exactly the unanimous rows whose parent is unanimous, that every
   item is `model_panel`, and the family separation. A set without a ledger must be author-confirmed; a
   mixed set is refused. Two raters may not give the same sheet.
   - **What CI cannot check.** The draft and the sheets are not committed (they hold rejected claims and
     abstract text), so the draft and sheet hashes, the completeness of the ledger's rows and which vote
     column is whose are **self-reported**. They are checked once, locally, by `apply-audit`, which reads
     the draft and every sheet. `traps verify` runs the same I79 check as CI before any call.
9. **Not reproducible.** Subagent runs cannot be replayed. The sheet sha256s are logged in the ledger and
   in dev-log S13, and the votes are self-reported, like every committed result.
10. **The author path is unchanged.** One `--sheet` with no `--rater` writes an author-confirmed set and
    no ledger, for a future expert or author who can audit.

## Consequences

- **Positive:**
  - The proof checkpoint can run before the hackathon without a false provenance label.
  - Who confirmed what is recomputable from committed data, and the rater rules are checked, not trusted.
  - The predeclared bias and reporting rules keep a silver-standard rate from being read as accuracy.
- **Negative / costs:**
  - The catch rate is conditional on LLM agreement and probably inflated (decision 4).
  - Unanimity shrinks the set; some kinds may be too small to say much.
  - Isolation is instructed, not enforced, and the runs cannot be reproduced.
  - Two LLMs from other families can still share the verifier's blind spots.
- **Follow-ups:**
  - Expert confirmation of a dev-v2 (backlog), the only set that may be called ground truth.
  - Trap prompt v2 and sieve fixes for the writer problems the discarded advisory pointed at (backlog);
    these apply to a new draft, never to dev-v1.
