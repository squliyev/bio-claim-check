# Handoff: how to continue this project

**Read this first** if you are a new agent or contributor picking up the work. Then read
[AGENTS.md](../AGENTS.md) (the rules), [roadmap.md](roadmap.md) (the plan) and the latest
`docs/dev-log/Sxx.md` (what just happened). Internal reference notes used for planning are kept outside
the repo; ask the maintainer for the rows relevant to your session.

## 1. Where things stand

- Done: S01, S02, S02b, S03, S04, S05, S05b, S06, S07a, the rule audit, S07b, S08, S08b, S09, S10, S11, S12a,
  S12b, S12c (tag `prompts-frozen-v2`). **S13 code is done** (ADR 0022, 0023); its data step is not (section 4).
  CI is green on `main`.
- **Next: finish S13** (the model-panel run, then commit the dev set), with the maintainer's
  test-split audit in parallel (section 4). Then
  the demo track: proof checkpoint → S17a (slim UI) → H1, then back to S14 ([roadmap](roadmap.md#demo-track-s13--proof--s17a--h1-then-back-to-s14)).
- Next free ids: invariant **I80**, ADR **0024**.
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

## 4. Next: finish S13 (dev trap set), with the test-split audit in parallel

**In parallel (maintainer, not an agent session):** the test-split eligibility audit and the
unanswerable check. It gates only test-split traps. The test audit is gated on the active freeze (I74). For each of the 5 scored kinds in
`datasets/corpus.yaml`, the author reads the first `audit_n` (50) candidates in the public order:

```bash
uv run bio-claim-check corpus audit-sheet --kind <kind> --split test   # recomputes freeze v2, refuses if stale
# fill in decision (confirm/reject) and a reason for every reject
uv run bio-claim-check corpus apply-audit --kind <kind> --split test --sheet var/audit/test-<kind>.csv
```

- The sheet is built from the local cache only (`var/cache.sqlite`); a missing page exits with a cache miss.
- `apply-audit` writes `datasets/audit/test/<kind>.json` once. `SEALED` does not cover that folder; the
  audit manifest deferred in S07b is due once the audits exist.
- The test unanswerable check has no tooling. It uses the dev rubric in [data-card.md](data-card.md) §5.
- An agent may run these commands but never reads a test sheet or test abstract, and never commits a sheet
  (abstract text).

**Finishing S13 (the dev trap set, [ADR 0022](adr/0022-trap-set-and-outcomes.md)):**

Done:
- The maintainer confirmed `TRAP_PROMPT` and ADR 0022 decision 8.
- Live drafting finished with a top-up to `--per-kind 20`. Draft: `var/traps/dev-draft-20-b222f76d60fb.jsonl`.
  Candidates: 9, 15, 17, 18 and 19 model traps per kind, plus 21 direction swaps (dev-log S13).

- The maintainer is not a biomedical researcher, so the author audit was replaced by a **two-model panel**
  (ADR 0023, I79): gemini-4-argon and grok-4.7 at high reasoning effort, unanimous only, a **silver
  standard**. The code is in commit F.
- An advisory pass by gemini-4-argon read `VERIFY_PROMPT`, so it is discarded (ADR 0023 §7).

Next (announced to the maintainer first):

```bash
# 1. delete the discarded advisory files
rm var/audit/traps-dev-b222f76d60fb.advisory.csv var/audit/traps-dev-b222f76d60fb.advisory-summary.md
# 2. one isolated folder per rater, holding only the protocol and a blank copy of the sheet
for r in gemini-4-argon grok-4.7; do mkdir -p var/panel/$r
  cp docs/protocols/trap-panel-v1.md var/panel/$r/protocol.md
  cp var/audit/traps-dev-b222f76d60fb.csv var/panel/$r/sheet.csv; done
# 3. run both raters as subagents in parallel (model = the rater id, high effort), each given the protocol
#    verbatim and told to read and write only its own folder; then:
uv run bio-claim-check traps apply-audit --draft var/traps/dev-draft-20-b222f76d60fb.jsonl \
  --sheet var/panel/gemini-4-argon/sheet.csv --rater gemini-4-argon \
  --sheet var/panel/grok-4.7/sheet.csv --rater grok-4.7
# 4. commit G: traps/dev-v1.jsonl and traps/dev-v1.panel.json; fill the dev-log S13 flow and 2x2 tables
```

- The protocol `docs/protocols/trap-panel-v1.md` is hashed into the ledger; never edit it after the run.
- The cohort is fixed at the 177 candidates. Nothing is topped up or replaced after the panel.
- Report per ADR 0023 §5: model traps primary, rule floor apart, numerators and denominators per kind and
  generator, the attrition flow. Never call dev-v1 ground truth or expert-labelled.
- `background_as_result` is capped at 9 (ADR 0022 §6). A kind still short of 12 confirmed traps after the
  panel is reported as short, not topped up (ADR 0023 §3).
- The draft, the sheet and the LLM cache (`var/cache.sqlite`) are all local. If only the draft or the sheet is
  lost, rerun `generate --per-kind 20` with a budget of 180: every call is a cache hit, so the draft is
  identical. If the cache is lost too, the drafts change, and the counts above no longer apply.
- `traps verify` is the proof checkpoint's step, not S13's. It refuses unless this code is the active
  freeze. Use `--record` once the counts have been read.
- Never commit a draft or a sheet: drafts list gate problems, and sheets hold abstract text.
  `tests/arch/test_trap_set.py` allows only sets, their panel ledgers, results and the README under `traps/`.

**Bindings from S12b and S12c (must hold):**
- Do not edit a judge file without a new freeze (ADR 0020). S13's trap generator lives outside
  `JUDGE_FILES`. The challenge set has run twice, its limit, so a new judge also needs a new set or an ADR.
- Prompt and rule-pack text must not name a question's topic (I75, ADR 0021).
- The challenge set is a regression check, not accuracy. Never report its 15/16 as an accuracy figure.
- Negation: `claim_shares_negation` false blocks are known (backlog C4). They are safe (`needs_review`).
- Dev numbers stay exploratory; test numbers come only after `protocol-v1` (S15).

**Exit:** the roadmap's S13 row; `make verify` and CI green.

## 5. Engine contracts you build on (S08–S12c)

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
- **S12c:** `tests/arch/test_prompt_neutrality.py` (I75); rule pack `0.2.0`; challenge results in
  `challenge/results/<freeze>.json`; `challenge run --record` and `freeze write` default to `ACTIVE_FREEZE`
  (ADR 0021). `features/baselines/` is an empty package for S14.
- **S13:** `features/contracts/outcome.py` (`PairOutcome`, read by challenge, traps and later S16).
  `features/traps/` is the full slice: sampling, the validity gate, the rule floor, the audit sheet and counts
  (all pure), plus `LlmTrapWriter` with `TRAP_PROMPT`. `app/usecases/traps.py` holds `generate`,
  `sheet_for`, `apply_audit`, `verify_set`, and `set_problems`/`result_problems` (I76–I78). Commands:
  `traps generate | audit-sheet | apply-audit | verify [--record]` (ADR 0022). The neutrality guard (I75)
  now finds every `PromptTemplate` under `features` by kind.

## 6. Bindings for later sessions

- **Before test-split traps:** the maintainer runs the test-split eligibility audit and unanswerable check; the
  audit records the active `freeze_sha256` (computed, never typed).
- **S17a (demo track):** layered Streamlit UI (backlog B4): Ask and Trust report pages only; reads `Report` +
  `RunManifest`; no trace view; Docker offline mode disables live controls; cached runs are regenerated after
  contract changes (no migrations); stays outside `JUDGE_FILES`. Writes the UI ADR.
- **H1:** decides what is shown on the day; option C (no claimcheck results on the day, no numbers) holds
  unless changed by ADR. Trap papers from dev or outside the corpus, checked against the test split by id only.
- **S17b:** Benchmark page, Markdown export, trap-outcome view.
- **S15:** protocol hashes must equal `prompts-frozen-v2`, or each deviation is disclosed.
- **S16/S19:** a pre-flight token estimate is a labelled heuristic range, never mixed with measured usage
  and never turned into a money estimate without a defensible price.

## 7. Rules that are easy to break

- Never print or commit `.env`, keys, real endpoints or personal data.
- Never weaken a check to pass; every suppression needs a one-line reason (guarded).
- Never report a number the code did not produce; dev numbers are exploratory; author-labelled is not
  expert-labelled.
- Never copy code from other codebases.

## 8. Gotchas (each has cost a session time)

- **Judge files are wider than the verifier.** `JUDGE_FILES` also holds the answer prompts and agents,
  `contracts/labels.py`, `contracts/verdict.py`, `common/negation.py`, `common/text.py` and the codecs. A new
  label or a verdict change breaks freeze v2; put trap-only types elsewhere.
- **No test ids outside `datasets/`.** The seal guard scans tracked *and staged* files. Write "a test
  question", never its id or PMID. Dev ids are fine.
- **A rule-pack edit changes run ids.** Update the expected ids in `tests/unit/app/test_cli_characterisation.py`.
- **New example or prompt topics** must appear in no question, query or source MeSH of either split (I75
  matches exact terms only).
- **Pinned bytes move with `git mv`** (freeze records, challenge results), never by rewriting.
- **Replays need the local cache.** `var/cache.sqlite` is git-ignored and machine-local; on another machine
  `BCC_CACHE_MODE=read-only` fails closed.
- **Live calls cost money.** Announce the call count first; re-runs use `BCC_CACHE_MODE=read-only`.

## 9. Useful commands

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
