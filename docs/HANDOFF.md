# Handoff: how to continue this project

**Read this first** if you are a new agent or contributor picking up the work. Then read
[AGENTS.md](../AGENTS.md) (the rules), [roadmap.md](roadmap.md) (the plan) and the latest
`docs/dev-log/Sxx.md` (what just happened). Internal reference notes used for planning are kept outside
the repo; ask the maintainer for the rows relevant to your session.

## 1. Where things stand

- Done: S01, S02, S02b, S03, S04, S05, S05b, S06, S07a, the rule audit, S07b, S08, S08b, S09, S10, S11, S12a.
  CI is green on `main`.
- **Next session: S12b, verifier tuning on dev and the prompt freeze** (section 4).
- Next free ids: invariant **I72**, ADR **0020**.
- The evaluation dataset in `datasets/` is **sealed** (`datasets/SEALED`, tag `prereg-corpus-v1`). Do not
  edit it. Prompt and rule-pack tuning (S10, S12a, S12b) may use **dev-split sources only**.

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

## 4. Next: S12b — verifier tuning and the prompt freeze

**Goal:** a dev smoke gold set that runs in CI, verifier and near-threshold tuning on dev sources only, the
freeze record and test export (ADR 0011), and the tag `prompts-frozen-v1`.

**Bindings from earlier sessions (must hold):**
- Dev-split sources only (`run --dev QUESTION_ID`, `dev_papers`); drop and count anything else.
- A change to `VERIFY_PROMPT`, an answer prompt or the rule pack changes the run id (declared LLMs, I71);
  a change to the negation rules bumps `NEGATION_RULES`.
- The verifier sees only `VerifyPayload` (I69); keep the failure mapping of ADR 0019 (I70).
- S12a live observation: on a metformin question the verifier said `supported` with a located quote, and
  the pair still went to `needs_review`: the sentence-level negation detector (conservative by design) saw
  "no effect was observed for insulin…" in the same sentence. Measure how often this happens on dev before
  deciding whether a clause-level rule (a `NEGATION_RULES` bump) is worth it.
- Claude's `max_output_tokens=8192` was kept: verifier replies were ~200 tokens; revisit if tuning
  changes the output.
- Money stays "unpriced" while `ModelSpec.price is None`; never 0.

**Exit:** the roadmap's S12b row; `make verify` and CI green.

## 5. Engine contracts you build on (S08–S11)

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

## 6. Bindings for later sessions

- **S12b:** see section 4. Tag `prompts-frozen-v1` only after the dev smoke gold set is green in CI.
- **Before S13:** the maintainer runs the test-split eligibility audit and unanswerable check; the audit
  records the frozen prompts hash.
- **S17:** layered Streamlit UI (backlog B4).
- **S15:** protocol hashes must equal `prompts-frozen-v1`, or each deviation is disclosed.
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
gh run list --limit 3
```
