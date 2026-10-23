# ADR 0019 — The LLM verifier, the first live `run` and the retraction re-check

- **Status:** Accepted
- **Date:** 2026-10-23
- **Supersedes / Extends:** extends [ADR 0006](./0006-two-axis-verdict-and-disposition.md) (who fills the
  label), [ADR 0017](./0017-answer-agent-and-deterministic-checks.md) (the live answer feeds `run`) and
  [ADR 0018](./0018-run-record.md) (declared LLMs in the manifest)
- **Related:** [ADR 0005](./0005-quote-location-fails-closed.md), [ADR 0011](./0011-sieve-v2-and-sealed-dataset.md),
  [ADR 0012](./0012-llm-engine-runner-and-cost.md), [ADR 0015](./0015-llm-agent-base.md)
- **Enforced by:** `tests/unit/features/test_verify_isolation.py` · `tests/unit/features/test_llm_verifier.py` · `tests/contract/test_verifier_contract.py` · `tests/unit/features/test_verify_prompts.py` · `tests/unit/features/test_report.py` · `tests/unit/app/test_build_models.py::test_every_deployment_names_who_trained_it` · `tests/unit/app/test_cli_run_live.py` · `tests/unit/app/test_retractions.py`

## Context

Until S12a, `run` worked only with `--fake`, and verdicts came from a scripted verifier. A real verifier
raises four questions. What may it see? Which of its failures count against one (claim, source) pair, and
which mean that the run itself is broken? How does a reader learn that the answerer and the verifier may
share blind spots? And how can a published run be re-checked for retractions without changing it?

## Decision

1. **One isolated call per pair.** `VerifyLlmAgent` (named `verifier`) gets a `VerifyPayload`: the claim
   text, the paper title, the cleaned abstract and the rule pack, and nothing else from the run (no
   question, other claims or papers, ids, MeSH, authors or rule references). The prompt renders the
   paper and the judgement fields of each rule as JSON data. It defines the four labels in precedence
   order and asks for a verbatim quote. Code still decides the evidence status and the negation through
   `Verdict.finalise` against the abstract (ADR 0005).
2. **Failure mapping.** Only failures of this pair's output are counted per pair as a `VerifierFailure`:
   `INVALID_OUTPUT` and `TRUNCATED` → `structured_output`; `CONTENT_FILTERED` (a filtered response, or a
   filtered prompt, which the runner raises as the same error) → `content_filtered`. Every other error
   propagates and stops the run, with a failed ledger row and no manifest: any provider status, transport,
   an unexpected response, the budget, the cache, or a bug in our request. `provider_error` is not
   produced by the LLM verifier, since no provider status is known to belong to one pair.
3. **Model families.** `ModelSpec.family` (`common.model_family.ModelFamily`: `openai`, `anthropic`,
   `moonshot`; the stored report validates against the same enum) records
   who trained a deployment; the provider that serves it is a separate field. A live report holds
   `models` = {answerer, verifier: {deployment, family}} and a computed `same_family`. `run` warns when it
   is true. Nothing is refused. A fake report has `models: null`.
4. **Provenance and notice.** `provenance` is `fake` or `live`. The notice is derived from it. The live
   notice says the labels are model judgements, not expert review.
5. **Declared LLMs.** `RunDetails.declared_llm` (required for every live command, including `answer dev`;
   empty for a fake run) lists, per role, the agent, provider, deployment, model
   version and prompt hash, taken from the wired agents rather than from events. A prompt change
   therefore changes the run id even when no verifier call finished.
6. **One flow.** `run QUESTION` (live) and `run --dev QUESTION_ID` (the sealed dev pool, through
   `dev_papers`) both go through `check_answer`. Both use `Settings.var_dir` and one `CallBudget` that
   covers the answerer and the verifier. A full run needs about 1 + pairs calls.
   - The dev artifact is a `DevRunRecord`: the report, the kept ids, the usable count and the drops by
     reason.
   - `--var-dir` is for fake runs only. `--dataset` is for dev runs only, and `--env-file` for live and
     dev runs. A wrong combination exits INPUT.
7. **Retraction re-check.** `retractions RUN_ID` is a separate command that never touches `runs/`.
   - **Before any request**, it checks that the id matches `^[0-9a-f]{16}$`, that the manifest parses
     and hashes to the id, that the artifact is `report.json` with the recorded hash, that the report
     parses, and that the manifest and the report both say it is a live `run`. Fake and dev runs are refused, and every refusal is
     `retractions.input`.
   - It then asks `BaseLiteratureSource.retraction_status` about the sorted, unique cited `MED:` ids,
     including ids that were never retrieved. The request uses no citable filters, goes in chunks of
     at most 100 and is uncached. An unexpected or duplicate record is an error.
   - Each row records `retracted_in_run` (`None` if not retrieved) and `retracted_now` (`None` if not
     found). The record is written to `var/retractions/<run_id>-<UTC>-<n>.json` by exclusive create.
     `checked_at` comes from the clock. There is no ledger row and no LLM.

## Consequences

- **Positive:** a verifier cannot be swayed by the question or by other pairs. A broken provider or
  schema cannot pose as a column of scientific failures. A reader sees when both models come from one
  family. A run can be re-checked for retractions while its run id still holds (I65).
- **Negative / costs:**
  - One call per pair is the most expensive design; the budget caps it.
  - Same-family runs are only flagged, not refused.
  - A provider outage on one pair loses the whole run (retrying is cheap from the cache).
  - The retraction source grew a by-id method instead of getting its own port, because the backend and
    its parser are shared.
- **Follow-ups:** S12b tunes the verifier prompt and the negation detector on dev, runs the dev smoke
  gold set in CI and tags `prompts-frozen-v1`. Backlog A12 (Anthropic's prompt-filter shape) still applies to
  the verifier on Claude.
