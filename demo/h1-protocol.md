# H1 demo papers: the predeclared protocol

This protocol was committed **before** any shortlisted abstract was read and before any verifier call.
The picks and claims follow in `demo/h1-trap-papers.json`, in a later commit. These are purpose-built demo
cases. They are not sampled, they are not an estimate, and they are not expert-labelled. None of the
results is shown on the day (option C, ROADMAP §1.2).

## Selection
- Kinds, with the sieve rule for each:
  - `preclinical_to_clinical` (`animals_not_humans`)
  - `background_as_result` (`prior_finding`)
  - `nonsignificant_as_effect` (`null_result`): "a null result stated as an effect". The idea's
    surrogate-endpoint example has no sieve kind, so it is not implemented, and this kind is never called
    a surrogate endpoint.
- The pool for each kind is the dev entries with that rule, minus every source or cluster already used in
  `challenge/dev-v1.jsonl` or `traps/dev-v1.jsonl`.
- The order is `audit_order` with the corpus's public `audit_salt`. The shortlist is the first 3
  (`tests/support/demo_pick.py`).

## Eligibility (applied in order; the first eligible paper is the pick)
1. The fetched abstract's sha256 equals the sealed `abstract_sha256`.
2. The abstract has the span the kind needs:
   - preclinical: a result in animals or cells;
   - background: a finding the abstract presents as prior or known work;
   - null result: a result the abstract reports as not significant, or as no difference.
3. That span is understandable without the full text.

Every rejected paper is recorded with its reason. If no shortlisted paper is eligible, the kind is **not
prepared**, and that is disclosed. Nothing is swapped in from outside the shortlist.

## Claims (written before any verifier call)
Write the faithful claim first. Then apply only the change for the kind:
- **Preclinical.** The faithful claim keeps the species or model. The overstated claim drops it and states
  the effect for patients.
- **Background.** The faithful claim attributes the finding to prior work. The overstated claim attributes
  it to this study.
- **Null result.** The faithful claim keeps the non-significance. The overstated claim states an effect.

Both claims must pass `claim_problems` (at most 30 words, no 8-word copy of the abstract, no rule-pack
echo) and `pair_problems`. The claims are drafted by the coding agent, not by a domain expert, and they
are labelled that way.

## Recording
- Six live `check` calls, one per claim.
- A complete six-row table: paper, role, kind, disposition.
- No aggregate rate, no tuning, and no swapped paper. A miss is disclosed as it is.

## Amendment (H1 commit C, after the checks)
The implementation review found that `used_ids` (B1) collected the prior **sources** but not their
**clusters**, so the code was weaker than this protocol's "source or cluster" wording. The code now matches
the text. Re-running the corrected rule gives the same three picks, so B2 and the six checks stand. This
amendment changes no pick and no claim.
