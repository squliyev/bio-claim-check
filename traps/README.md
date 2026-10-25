# Trap sets

Planted misreadings with predeclared expected outcomes, for measuring what the frozen verifier catches
([ADR 0022](../docs/adr/0022-trap-set-and-outcomes.md); confirmation by a model panel:
[ADR 0023](../docs/adr/0023-model-panel-confirmation.md)).

## What is here

- `dev-v1.jsonl` (once the panel has run): the dev trap set, one `TrapItem` per line, sorted by id. It is written by
  `traps apply-audit` from the panel's sheets and is never edited by hand.
- `dev-v1.panel.json` (likewise): the panel ledger, each rater's vote on each candidate with the draft, protocol and
  sheet hashes. No reasons and no claim text.
- `results/<freeze>-<set>.json`: a `TrapResult` from `traps verify --record`, with one outcome per item and
  the disposition counts per kind, role and generator.

Nothing else belongs here. Drafts and audit sheets stay under the git-ignored var dir: drafts list gate
problems, and sheets hold abstract text (ADR 0008). `tests/arch/test_trap_set.py` checks every file here on
every CI run (I76, I77, I79).

## How a set is made

1. `traps generate --per-kind N` samples dev sources per scored kind, deterministically. One model call per
   source drafts a supported **parent** and a **trap** that commits the kind. Up to three **rule-floor**
   traps (direction, operator or dose swaps) are derived from the parent. A pure gate drops claims over
   30 words, claims copying the abstract, and claims echoing a rule-pack example.
2. `traps audit-sheet` exports the candidates with their abstracts, bound to the draft's sha256.
3. Each rater decides every row in its own copy, under `docs/protocols/trap-panel-v1.md`. Is the parent
   supported by the abstract? Is the trap a valid instance of its kind or rule, in the writer's own words?
   A rejection needs a reason. (An author who can audit uses one sheet and no `--rater` instead.)
4. `traps apply-audit --sheet A --rater R1 --sheet B --rater R2` writes the rows every rater confirmed,
   and the ledger. A trap whose parent any rater rejected is dropped.

## What it must not be used for

- **Not naturalistic spin.** One call writes both claims, a controlled paired design that favours lexical
  contrasts. Report trap catch rates separately from natural overstatement.
- **Not ground truth, not accuracy, and not test numbers.** dev-v1 is a silver standard: a two-model panel
  confirms it unanimously (`confirmed_by = model_panel`, `origin = model`; ADR 0023), which probably
  keeps the easier traps. Dev only and exploratory. Test traps need a later ADR and the test audit.
- **Not for tuning.** The judge is frozen. `traps verify` refuses unless this code is the active freeze.
