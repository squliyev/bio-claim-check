# ADR 0025 — A single-claim check is a recorded run kind

- **Status:** Accepted
- **Date:** 2026-10-26
- **Supersedes / Extends:** extends [ADR 0018](./0018-run-record.md) (the run record gains a second
  artifact kind and a second inputs model)
- **Related:** [ADR 0008](./0008-citable-sources-medline-abstracts.md) (what counts as citable),
  [ADR 0006](./0006-two-axis-verdict-and-disposition.md) (dispositions)
- **Enforced by:** `tests/unit/app/test_check_claim.py` · `tests/unit/app/test_claim_check_model.py`
  (integrity, R1) · `tests/unit/app/test_published_run.py` (hash chain and kinds, R5) ·
  `tests/unit/app/test_recorded.py` (one recording path, R4) · `tests/unit/app/test_cli_check.py` ·
  `tests/contract/test_literature_source_contract.py` (`fetch`)

## Context

The demo (roadmap, S17a) needs to show the verifier on one claim a person chooses, against one paper they
name, without depending on what an answering model happens to write. A `Report` cannot hold this: it has a
question, an answer mode and an answerer, and its papers came from a search. Writing such a check outside
the run record would give the UI results with no manifest, no ledger row and no hash chain, so a reader
could not tell a recorded check from a typed one.

## Decision

1. **Fetch by id.** `BaseLiteratureSource.fetch(source_id)` returns the one citable paper with that id,
   through the same cache as `search`, or raises `PaperNotFoundError` / `NotCitableError` (with the
   `RejectReason`). Europe PMC accepts `MED:<pmid>` only and refuses a record for another id.
2. **Input.** A live check is a claim (non-blank, at most 1000 characters, no control characters) and a
   PMID parsed by one strict function, `parse_pmid` (1 to 9 ASCII digits, no leading zero, an optional
   `PMID`/`MED` prefix). Both are checked before any request. The claim gets id `c1`.
3. **Artifact.** `ClaimCheck` (`check.json`) holds the provenance, the claim and its one pair, the paper,
   and the verifier model (live only). Its validator gives it a `Report`'s integrity: the claim cites
   exactly the paper; the pair is a verdict or a verifier failure, never "not retrieved"; a verdict's
   evidence re-derives from the stored abstract; a fake check cites only `FAKE:` papers. Its notice says
   it is an LLM's judgement (live) or fictional (fake).
4. **Record.** Command `check`, with `CheckInputs(kind="check", claim_sha256, source_id)` in the manifest.
   It is a separate model so that `run` manifests keep their exact bytes. A live check declares only the
   verifier role (I71). A fictional check takes a scripted claim on a `FAKE:` paper, never a PMID.
5. **One path.** `app/recorded.py` (`record_question`, `record_check`) is the only code that records a
   `run` (not `--dev`) or a `check`; the CLI and the UI both call it. A process-wide lock serialises
   recorded commands in one process; two processes at once stay unsupported.
6. **One loader.** `app/usecases/published_run.load_published` checks the whole chain before anything is
   shown: the manifest hashes to the run id, the artifact to the manifest, the artifact name and inputs
   match the command, the artifact parses as its kind, its provenance matches, and a check checks what its
   manifest names. `retractions` uses it too; a retraction re-check of a `check` run is not built yet.

## Consequences

- **Positive:** the demo can show a guaranteed overstated example with full provenance; the UI and the CLI
  cannot record differently; every shown run is verified against its id.
- **Negative / costs:** a second artifact kind for every reader to handle; the `RunDetails.inputs` union.
- **Follow-ups:** retraction re-check of `check` runs (backlog); a recorded Europe PMC by-id fixture from a
  real response (S17a used fictional records).
