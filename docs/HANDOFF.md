# Handoff: how to continue this project

**Read this first** if you are a new agent or contributor picking up the work. Then read
[AGENTS.md](../AGENTS.md) (the rules), [roadmap.md](roadmap.md) (the plan) and the latest
`docs/dev-log/Sxx.md` (what just happened). Internal reference notes used for planning are kept outside
the repo; ask the maintainer for the rows relevant to your session.

## 1. Where things stand

- Done: S01, S02, S02b, S03, S04, S05, S05b, S06, S07a, the rule audit, S07b, S08, S08b, S09, S10, S11, S12a,
  S12b, S12c (tag `prompts-frozen-v2`), S13 (ADR 0022, 0023; `traps/dev-v1.jsonl`, a silver standard), the
  proof checkpoint S13p (ADR 0024, I80; verdict **ADJUST**, dev-log S13p), S17a (ADR 0025, I81–I83,
  dev-log S17a) and H1 (I84, dev-log H1). S17a added the layered Streamlit UI, `check` (one claim against
  one paper by PMID) and `ui`. H1 closed the demo track: live `check` and `run` refuse sealed test-split
  papers, three dev demo papers were predeclared and checked once, and option C holds. CI is green on `main`.
- **Next: S14**, baselines (section 4). The demo track is done; the hackathon prep is private (outside
  the repo). The maintainer's test-split audit runs in parallel.
- Next free ids: invariant **I85**, ADR **0026**.
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

## 4. Next: S14, baselines (test-split audit in parallel)

**S14** (roadmap row S14): AlwaysFlag, a MeSH-cue baseline, an optional NLI baseline, and a shared verifier
contract suite.
- `features/baselines/` is an empty package waiting for it. `tests/contract/test_verifier_contract.py` is
  the existing verifier suite to extend or share.
- Follow the slice order in AGENTS.md: port, models, pure logic, in-memory or scripted, contract suite, and
  only then a backend. Any baseline with a model or a new dependency is classified in
  `tests/arch/test_dependency_policy.py`.
- ADR 0010 notes that the MeSH-cue baseline shares the sieve's signal; say so wherever it is reported.
- A baseline is not a judge file. Keep it outside `JUDGE_FILES` so freeze v2 holds.
- Write the S14 plan first, with code sketches and a file tree (AGENTS.md), and have it reviewed.

**Demo (H1, done):** option C holds. Nothing claimcheck produces is shown on 1 Dec, so there is no UI on the
day and no numbers. The pitch slide is hand-made. The maintainer's private prep (slide text, pitch notes and
disclosure, laptop checklist, snippet sheet) is outside the repo. Do not bring any of it into the repo.

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

**What the proof checkpoint found (S13p, [ADR 0024](adr/0024-proof-checkpoint-go-adjust.md), dev-log S13p):**

- `traps/results/v2-dev-v1.json`, recorded once under freeze v2. On dev-v1 (38 items, a silver standard,
  ADR 0023), as k of n:
  - model traps: 14 of 15 flagged, 1 `needs_review`, none passed;
  - parents: 0 of 16 flagged, 10 of 16 passed, 6 `needs_review` (3 of them nonsignificant_as_effect);
  - rule floor: 5 of 7 flagged;
  - failed: 0 of 38.
- **Verdict: ADJUST.** The predeclared rule needs at least 12 of 16 parents passed. That condition was added
  by the plan review before the run; the maintainer's original three conditions would have given GO.
  This is disclosed in S13p. I80 checks that the stated verdict is the one code gives.
- **Never:**
  - tune the judge on these outcomes;
  - rerun or re-record dev-v1 under v2 (`--record` refuses);
  - quote these as rates or as accuracy.
  A prompt change goes only through a new freeze via the challenge set, and a later freeze needs its own
  predeclared rule.

**What S17a built** (dev-log S17a, commits `d7e1525`…`1f95058`):
- `BaseLiteratureSource.fetch(source_id)`: Europe PMC accepts strict `MED:<pmid>`, cached, with the citable
  policy; the in-memory source has it too.
- `ClaimCheck` (`check.json`, with an integrity validator) and `CheckInputs`, a manifest union under which
  old `run` manifest bytes are unchanged.
- `app/usecases/check_claim.py` (`parse_pmid`, `check_claim`) and `app/recorded.py` (`record_question`,
  `record_check`, the process lock, `UI_ERRORS`). Both the CLI and the UI go through `recorded`.
- `app/ui/`:
  - `protocol.py`: ledger list and About view, from bytes;
  - `run_view.py`: everything escaped, highlights only where `locate_quote` agrees;
  - `error_copy.py`: curated copy;
  - `page.py`: the only streamlit importer.
- Offline mode turns Live into **Replay**, read-only cache, instead of disabling it.
- The About page computes ADJUST with `proof_checkpoint.checkpoint` and shows every row, as k of n.
- The UI stays outside `JUDGE_FILES`, so freeze v2 holds.

Still true for traps:
- Never commit a draft or a sheet: drafts list gate problems, and sheets hold abstract text.
  `tests/arch/test_trap_set.py` allows only sets, their panel ledgers, results and the README under `traps/`.
- The local panel sheets (`var/panel/<rater>/sheet.csv`) are not committed; their sha256s are in the ledger.

**Bindings from S12b and S12c (must hold):**
- Do not edit a judge file without a new freeze (ADR 0020). S13's trap generator lives outside
  `JUDGE_FILES`. The challenge set has run twice, its limit, so a new judge also needs a new set or an ADR.
- Prompt and rule-pack text must not name a question's topic (I75, ADR 0021).
- The challenge set is a regression check, not accuracy. Never report its 15/16 as an accuracy figure.
- Negation: `claim_shares_negation` false blocks are known (backlog C4). They are safe (`needs_review`).
- Dev numbers stay exploratory; test numbers come only after `protocol-v1` (S15).

**What H1 built** (dev-log H1, commits `a91e266`, `cc49483`, `6e11d3b` and the docs commit):
- **I84:** `container.sealed_test_ids(dataset)` runs the full seal check, then returns every test
  `source_id` and `cluster_id`. Live `check` refuses one before the fetch; live `run` refuses a search that
  returns one before the answerer (`HeldOutSourceError`, code `check.test_split`). `CheckPorts.closed_ids`
  and `RunPorts.closed_ids` are required. Only the fictional ports pass `frozenset()`.
- The live builders take `dataset=` (default `SEALED_DATASET`), and the seal check is their first
  statement. `run --dev --dataset X` passes `X`.
- The image copies `datasets/` (ids and hashes only), and `chmod`s it with `traps/` before `USER`
  (`tests/arch/test_dockerfile.py`).
- `demo/h1-protocol.md` and `demo/h1-trap-papers.json` hold the predeclared demo papers (dev only) and the
  claims; `tests/support/demo_pick.py` holds the rule, and `tests/arch/test_demo_papers.py` re-runs it.
  Never re-pick or re-check them to get a better result.

**Exit for S14:** its plan is reviewed, its slice follows the order above, and `make verify` and CI are
green.

## 5. Engine contracts you build on (S08–S17a)

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
- **S17a:** `BaseLiteratureSource.fetch`; `features/report/models.py::ClaimCheck`; `app/run_record.py::CheckInputs`;
  `app/usecases/check_claim.py` (`parse_pmid`, `check_claim`, `CheckPorts`); `app/usecases/published_run.py`
  (`load_published`, shared with retractions); `app/recorded.py` (`record_question`, `record_check`,
  `UI_ERRORS`, `_RECORD_LOCK`); `app/container.py::build_{fake,live}_check_ports`, `read_ledger`;
  `app/settings.py::UiSettings`, `CHECKPOINT_RESULT`; `app/ui/{protocol,run_view,error_copy,page}.py`.
  Commands: `check CLAIM --pmid N` (or `--fake EXAMPLE`), `ui [--port] [--address] [--env-file]`.
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
- **UI (S17a, built):** new pages go in `page.py` only, built from a pure view in `run_view.py`/`protocol.py`
  (I82). Every user-facing error needs copy (I83). Render HTML only through `st.html` with escaped views (I81).
  Cached runs are regenerated after contract changes; there are no migrations.
- **Demo (H1 done):** option C (no claimcheck results on the day, no numbers) holds unless changed by ADR.
  Any new demo paper comes from dev or from outside the corpus. Live `check` and `run` refuse test papers (I84).
- **S15:** a live `run` that retrieves a sealed paper refuses the whole question today (backlog B8). A
  filter that drops the paper changes which papers a run answers from, so it belongs with the protocol.
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
- **UI tests run the page in-process** (`streamlit.testing.v1.AppTest`). `tests/conftest.py` chdirs into an empty
  temp dir and strips `BCC_*`, so a test copies `traps/results/v2-dev-v1.json` in for About. After changing a
  radio, call `.run()` before reading widgets that depend on it.
- **Streamlit bound to 0.0.0.0 phones out** for the public IP unless `browser.serverAddress` is set; `ui`
  sets it. Plain `docker compose down` does not stop the profiled `offline` service; use
  `docker compose --profile offline down`.
- **Replay still needs `Settings`** (`BCC_CONTACT_EMAIL`), but no provider keys: read-only `build_models` builds
  no provider client.
- **A checkout can keep 0600 modes** (files written by `publish_once`). `COPY` keeps the mode, and the image
  runs as non-root, so a new runtime path needs both a `COPY` and the `chmod` line
  (`tests/arch/test_dockerfile.py`). CI's fresh checkout is 0644 and will not show it.
- **pytest collects any class named `Test*`**, even an imported error class. That is why the guard error is
  `HeldOutSourceError`.
- **Tests that build live ports run the full seal check** (about 1 s each). Pass `dataset=SEALED`
  (`tests.support.paths`), because `tests/conftest.py` chdirs into an empty folder.
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
uv run bio-claim-check check --fake o1                    # a fictional check, offline
uv run bio-claim-check check "<claim>" --pmid <dev PMID>  # live: one verifier call, recorded
uv run bio-claim-check ui                                 # http://localhost:8501
docker compose up offline                                 # the UI in replay mode (cache only)
uv run bio-claim-check corpus verify
uv run bio-claim-check challenge run                      # live; BCC_CACHE_MODE=read-only replays free
gh run list --limit 3
```
