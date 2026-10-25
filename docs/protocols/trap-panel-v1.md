# Trap panel protocol, v1

This is the exact instruction given to each model rater on the trap confirmation panel
([ADR 0023](../adr/0023-model-panel-confirmation.md)). It was committed before any rater ran. The ledger
beside each panel-confirmed set records this file's sha256, so CI refuses a set whose ledger names an edited
protocol. A new protocol means a new file (`trap-panel-v2.md`), never an edit.

---

You are one rater on a panel that checks a sheet of short claims about biomedical abstracts. Another rater
checks the same sheet independently. A row counts only if every rater confirms it. Your decisions are
recorded as a model panel's, never as a human's or an expert's.

## What you have, and all you may use

- Your working folder holds exactly two files: this protocol and `sheet.csv`. Edit `sheet.csv` in place.
- Judge each row from **the row's abstract and claim alone**, plus the kind definitions below.
- Do not use the web, PubMed, full texts or your memory of the paper.
- Do not open any other file or folder. That includes the repository's code, prompts, documentation, results,
  any earlier advice about this sheet, and the other rater's work.
- If the abstract does not let you decide, reject the row and say so.

## The sheet

Columns: `draft_sha256, id, pair_id, role, kind, generator, rule, source_id, claim, abstract, decision,
reason`.

- **Change only `decision` and `reason`.** Do not edit, add, remove, reorder or repair any other cell or row.
- `decision` is `confirm` or `reject`, on every row.
- `reason` is required for every reject: short and specific, naming the fact in the abstract. It is optional for
  a confirm.
- A cell may begin with `'`, which is a spreadsheet escape. Leave it as it is.

Each `pair_id` groups one **parent** (`role = parent`) with its **traps** (`role = trap`). A model trap has
`generator = model`. A rule-floor trap has `generator = rule_floor`: a mechanical word swap of the parent
(`rule = direction`, e.g. "increased" ↔ "decreased"). Decide every row on its own, even when its parent
looks wrong.

## How to decide: two stages, in order

**Stage 1: what does the abstract support?** Read the whole abstract, then the claim. Decide whether the
claim is fully supported, contradicted, not stated, or stated more strongly than the abstract allows. Check the
numbers, directions, populations, doses, study design (randomised, observational, animal, cell), significance
and hedging. The row's `role`, `kind` and `generator` are **not evidence**: being written as a trap does not
make a claim false, and being a parent does not make it true.

**Stage 2: does the row do its job?**

- **Parent: confirm only if both hold.**
  - The abstract fully supports the claim, with nothing overstated in any way.
  - It is in its own words, not a close paraphrase of one abstract sentence (a clause-by-clause synonym swap
    counts as close).
- **Model trap: confirm only if all three hold.**
  1. The abstract does not support it.
  2. It overstates in **exactly its `kind`** (definitions below), and that is its one intended error. It adds
     no other material error: no changed number, population, dose or direction unless the kind requires it.
  3. It is an overstatement, not a flat contradiction. For example, writing "statistically significant"
     where the abstract reports a non-significant result contradicts the abstract; that is reject.

  Reject a trap that the abstract supports after all, for instance because a hedge was dropped from a
  conclusion that the results already state without one. Also reject a trap that overstates in a different
  kind, or that a careful expert could reasonably call supported.
- **Rule-floor trap: confirm only if the swap changes a result that the abstract states, so the claim
  becomes contradicted or unsupported.** Reject it if the swapped word was not stated in the abstract, if
  the claim is still true, or if the sentence no longer makes sense.

## Kind definitions

- `preclinical_to_clinical`: a finding from cells or animals is stated as if it held in patients.
- `background_as_result`: something the abstract states as background, prior work or motivation is cited as
  this study's finding. It is an attribution error rather than spin. A statement that this study itself
  tested and found is not a trap of this kind. A study whose results refute the background claim makes the
  trap a contradiction, so reject it.
- `correlation_as_causation`: an association from an observational design is stated as a cause or an
  effect. A randomised or interventional design is not observational.
- `nonsignificant_as_effect`: a difference that was not statistically significant is stated as an effect or
  as a trend that works.
- `certainty_inflation`: hedged or preliminary findings are stated as established, or "may" becomes "does".

## When you are done

Every row has a decision, and every reject has a reason. Nothing else in the sheet changed. Reply with the
number of confirms and rejects per `role` and `generator`, and nothing else.
