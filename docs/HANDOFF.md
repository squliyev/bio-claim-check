# Handoff: how to continue this project

**Read this first** if you are a new agent or contributor picking up the work. Then read
[AGENTS.md](../AGENTS.md) (the rules), [roadmap.md](roadmap.md) (the plan) and the latest
`docs/dev-log/Sxx.md` (what just happened). Internal reference notes used for planning are kept outside
the repo; ask the maintainer for the rows relevant to your session.

## 1. Where things stand

- Done: S01, S02, S02b, S03, S04, S05, S05b, S06, S07a, the rule audit, S07b, S08, S08b, S09, S10, S11, S12a,
  S12b, S12c (tag `prompts-frozen-v2`).
  CI is green on `main`.
- **Next: the maintainer's test-split audit, then S13 (trap generator)** (section 4).
- Next free ids: invariant **I76**, ADR **0022**.
- The evaluation dataset in `datasets/` is **sealed** (`datasets/SEALED`, tag `prereg-corpus-v1`). Do not
  edit it. Prompt and rule-pack tuning (S10, S12a, S12b) may use **dev-split sources only**.
- The judge is **frozen** (`freeze/v2.json` active, ADR 0020, 0021). Any edit to a judge file (`app/freeze.py::JUDGE_FILES`),
  either model spec or `rapidfuzz` fails `tests/arch/test_active_freeze.py`. A new judge needs a new freeze
  record, a new pin and an ADR.

## 2. Start checklist

1. `git status` clean, `git pull`, `uv sync --frozen`.
2. `make verify` green before you change anything.
3. Read the session's section in [roadmap.md](roadmap.md), the bindings below, and the ADRs it touches.
4. Write the plan in the required format (section 3) and get the maintainer's answers to open questions.

## 3. Per-session process

Follow the process in [roadmap.md](roadmap.md#per-session-process-every-session). In short:

1. Plan: code sketches + an ASCII tree of every `+`/`~`/`−` file with `# because …`; decisions, tests,
   invariants, ADRs, out of scope, exit.
2. Ask the maintainer about real decisions.
3. Exactly **one plan review** by a paranoid-senior-engineer reviewer listing every suggestion (no cap),
   then your own triage per finding (adopt / adapt / reject as over-engineering) and a balance pass.
4. Implement; characterisation tests first when refactoring; `make verify` green.
5. Exactly **one implementation review** by the same reviewer brief, uncapped, triaged the same way.
   Record both triage tables in the dev-log.
6. Docs: ADR + index row, invariants, glossary, [error-codes.md](error-codes.md), backlog, dev-log,
   `make graph` (after import changes), `make schemas` (after contract changes).
7. Secret/IP scans clean; commit with a clear message; push; check CI with `gh run list`.

## 4. Next: the test-split audit (maintainer), then S13 — the trap generator

**Before S13 (maintainer, not an agent session):** the test-split eligibility audit and the unanswerable
check. The test audit is gated on the active freeze (I74):

```bash
uv run bio-claim-check corpus audit-sheet --kind <kind> --split test   # recomputes freeze v2, refuses if stale
uv run bio-claim-check corpus apply-audit --kind <kind> --split test --sheet var/audit/test-<kind>.csv
```

**S13 goal:** see the roadmap row (rule floor + model traps within eligibility, validity gate, audit
sheet, parent pairing, structural leakage test).

**Bindings from S12b and S12c (must hold):**
- Do not edit a judge file without a new freeze (ADR 0020). S13's trap generator lives outside
  `JUDGE_FILES`. The challenge set has run twice, its limit, so a new judge also needs a new set or an ADR.
- Prompt and rule-pack text must not name a question's topic (I75, ADR 0021).
- The challenge set is a regression check, not accuracy. Never report its 15/16 as an accuracy figure.
- Negation: `claim_shares_negation` false blocks are known (backlog C4). They are safe (`needs_review`).
- Dev numbers stay exploratory; test numbers come only after `protocol-v1` (S15).

**Exit:** the roadmap's S13 row; `make verify` and CI green.

## 5. Engine contracts you build on (S08–S12b)

- `engine/llm`: `LlmRequest`, `LlmResponse`, `Message`, `FinishReason`, `Usage`, `Price`, `Spend`,
  `cost()`, `ModelSpec`, `ModelCatalog`, `Provider`, `LlmCallError` (kinds: invalid output, truncated,
  content filtered), `BaseLlmClient`, `ScriptedLlmClient`, `CachingLlmClient`.
- `engine/pipeline`: `Invocation` (payload vs request: only `request` reaches a provider),
  request/response processor bases (`[EXTENSION POINT]`), `LlmRunner` (one repair, only on invalid
  output).
- `engine/prompts`: `PromptTemplate` (hash derived from text) and strict `render`.
- `app/settings.py`: `FoundrySettings`, `AnthropicSettings`, `OllamaSettings`; `app/models.py` holds the
  deployment facts; `app/container.py::build_models` fails at wiring on an unknown deployment or a live
  role without provider settings.
- **S09:** `engine/llm/{openai,anthropic}_llm_client.py` over pure codecs, `transport_policy` (our retries),
  typed `llm.*` errors, `LlmResponse.served_model`; `app/container.py::build_llm_clients`;
  `engine/agent/base_llm_agent.py` (`BaseLlmAgent`, `AgentResult`) and `ping_llm_agent.py`;
  `engine/events` (`PipelineEvent`, stage and LLM events, `EventEmitter`, in-memory and logging sinks);
  `app/events.py` (`AnyPipelineEvent`, `parse_event`); `common/base_clock.py` + scripted and system
  clocks. `bio-claim-check llm ping` checks deployments live; `make record-llm` re-records fixtures.
- **S10:** `features/answer/` (`StrictAnswerLlmAgent`, `OverEagerAnswerLlmAgent`, `LlmAnswerer`,
  `answer_models.to_claims`, `answer_prompts`), `features/checks/self_containment.py`,
  `common/negation.py` (`NEGATION_RULES`, stored in every `Verdict`), `features/corpus/dev_pool.py`,
  `app/usecases/answer_dev.py`, `app/container.py::build_dev_answer_ports`;
  `bio-claim-check answer dev QUESTION_ID --mode strict|over_eager` (ADR 0017).
- `common/canonical_json.py` for every hash and written JSON; `common/errors.py::BccError` with a stable
  `code` for every deliberate error (listed in [error-codes.md](error-codes.md)); logging goes to stderr
  through a redacting filter.
- **S11:** `app/run_record.py` (`RunManifest`, `LedgerRow`, `recording`, `RunRecorder`) wired by
  `app/container.py::record_run`; `engine/events/{jsonl,tee}_event_sink.py`, `call_tally.py`;
  `engine/llm/budgeted_llm_client.py` (`CallBudget`); `infrastructure/line_files.py`. Every attempt of
  both commands writes `var/events/*.jsonl` and a `var/ledger.jsonl` row; a success also publishes
  `var/runs/<run_id>/{artifact, manifest.json}` (ADR 0018).
- **S12a:** `features/verify/{verify_models, verify_prompts, verify_llm_agent, llm_verifier}.py`
  (`VerifyPayload`, `VERIFY_PROMPT`, `VerifyLlmAgent`, `LlmVerifier`); `common/model_family.py`
  (`ModelFamily`) and `ModelSpec.family`;
  `Report.provenance` (`fake`/`live`), `LIVE_NOTICE`, `Report.models` (`RunModels.same_family`);
  `RunDetails.declared_llm`; `app/usecases/run.py::check_answer`, `run_dev.py` (`DevRunRecord`),
  `answer_dev.py::dev_papers`; `BaseLiteratureSource.retraction_status`; `app/usecases/retractions.py`;
  `app/container.py::build_live_run_ports`. Commands: `run QUESTION`, `run --dev QUESTION_ID`,
  `retractions RUN_ID` (ADR 0019).
- **S12b:** `features/bench/challenge.py` (`ChallengeItem`, `ChallengeOutcome`, `ChallengeScore`,
  `score`); `app/freeze.py` (`JUDGE_FILES`, `JudgeInputs`, `FreezeRecord`, `FROZEN`, `ACTIVE_FREEZE`);
  `app/usecases/challenge.py` (`run_challenge`, `attestation_problems`); `app/container.py::current_judge`,
  `active_freeze_sha256`, `build_challenge_ports`; `corpus_audit` with `split`. Commands: `challenge run
  [--record]`, `freeze write`, `corpus audit-sheet|apply-audit --split test` (ADR 0020).

## 6. Bindings for later sessions

- **Before S13:** the maintainer runs the test-split eligibility audit and unanswerable check; the audit
  records the active `freeze_sha256` (computed, never typed).
- **S17:** layered Streamlit UI (backlog B4).
- **S15:** protocol hashes must equal `prompts-frozen-v2`, or each deviation is disclosed.
- **S16/S19:** a pre-flight token estimate is a labelled heuristic range, never mixed with measured usage
  and never turned into a money estimate without a defensible price.

## 7. Rules that are easy to break

- Never print or commit `.env`, keys, real endpoints or personal data.
- Never weaken a check to pass; every suppression needs a one-line reason (guarded).
- Never report a number the code did not produce; dev numbers are exploratory; author-labelled is not
  expert-labelled.
- Never copy code from other codebases.

## 8. Useful commands

```bash
make verify          # the gate: ruff, format, pyright strict, lint-imports, tests, core coverage
make graph           # regenerate docs/architecture/*.dot after import changes
make schemas         # regenerate schemas/ after contract changes
make live            # opt-in live tests (needs BCC_CONTACT_EMAIL and BCC_FOUNDRY__*)
make record-llm      # re-record scrubbed LLM fixtures (live, fictional text)
uv run bio-claim-check llm ping
uv run bio-claim-check answer dev glp1-q1 --mode strict   # live; BCC_CACHE_MODE=read-only replays free
uv run bio-claim-check run "Does OS-912 slow cognitive decline?" --fake
uv run bio-claim-check run glp1-q1 --dev --mode strict   # live over the dev pool; read-only replays free
uv run bio-claim-check run "<question>"                   # live answer + LLM verifier, recorded
uv run bio-claim-check retractions RUN_ID                 # re-check a live run's citations, uncached
uv run bio-claim-check corpus verify
uv run bio-claim-check challenge run                      # live; BCC_CACHE_MODE=read-only replays free
gh run list --limit 3
```
