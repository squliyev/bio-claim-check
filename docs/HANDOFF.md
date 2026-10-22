# Handoff: how to continue this project

**Read this first** if you are a new agent or contributor picking up the work. Then read
[AGENTS.md](../AGENTS.md) (the rules), [roadmap.md](roadmap.md) (the plan) and the latest
`docs/dev-log/Sxx.md` (what just happened). Internal reference notes used for planning are kept outside
the repo; ask the maintainer for the rows relevant to your session.

## 1. Where things stand

- Done: S01, S02, S02b, S03, S04, S05, S05b, S06, S07a, the rule audit, S07b, S08, S08b, S09.
  CI is green on `main`.
- **Next session: S10, the answer agent** (section 4).
- Next free ids: invariant **I61**, ADR **0017**.
- The evaluation dataset in `datasets/` is **sealed** (`datasets/SEALED`, tag `prereg-corpus-v1`). Do not
  edit it. Prompt and rule-pack tuning (S10, S12) may use **dev-split sources only**.

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
3. Exactly **one plan review** (problem hunting only), then your own triage per finding and a balance pass.
4. Implement; characterisation tests first when refactoring; `make verify` green.
5. Exactly **one implementation review**, triaged the same way. Record both triage tables in the dev-log.
6. Docs: ADR + index row, invariants, glossary, [error-codes.md](error-codes.md), backlog, dev-log,
   `make graph` (after import changes), `make schemas` (after contract changes).
7. Secret/IP scans clean; commit with a clear message; push; check CI with `gh run list`.

## 4. Next: S10 — answer agent

**Goal:** the first real feature agent. Given a question and retrieved sources, it writes an answer of
self-contained claims, each citing sources, in two modes (Strict / Over-eager), with stated non-scope and
abstention; plus the negation and self-containment checks and invented-citation detection.

**Planned shape (to be confirmed in the plan):**
- `features/answer/answer_llm_agent.py`: `AnswerLlmAgent(BaseLlmAgent[…, …])` declaring `name`, `prompt`,
  `output` and `variables` (ADR 0015). It joins `tests/contract/test_llm_agent_contract.py`.
- `features/answer/llm_answerer.py`: implements `BaseAnswerer` by **composing** the agent (no multiple
  inheritance); `app` wires the client, spec, emitter and processors.
- The answer prompt lives under the prompts package with a template hash; dev-split sources only.

**Bindings from earlier sessions (must hold):**
- Every LLM agent subclasses `BaseLlmAgent` and passes the agent contract suite (I57).
- Output models must be **strict-schema compatible** (every property required, no extra keys), or the
  OpenAI codec refuses the request (ADR 0014).
- Claude output is forced tool use without thinking; do not set `reasoning_effort` on Claude.
- Events never carry content (I59); new domain events join `app/events.py`'s union (I58).
- Tune on dev-split sources only; drop and count anything else.
- Kimi has no adapter yet (backlog A10): do not assign it a live role.

**Exit:** a Strict and an Over-eager answer run live on dev sources through the agent; offline tests on
scripted clients; `make verify` and CI green.

## 5. Engine contracts you build on (S08, S08b, S09)

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
- `common/canonical_json.py` for every hash and written JSON; `common/errors.py::BccError` with a stable
  `code` for every deliberate error (listed in [error-codes.md](error-codes.md)); logging goes to stderr
  through a redacting filter.

## 6. Bindings for later sessions

- **S10/S12:** use dev-split sources only; drop and count anything else. Negation check (S10) turns
  supported + located into `passed` only when clear. S12 maps LLM failure kinds to `FailureKind`, adds
  context isolation (a sentinel in the payload never appears in the request), re-checks retraction of
  every cited paper uncached, and ends with the tag `prompts-frozen-v1`.
- **Before S13:** the maintainer runs the test-split eligibility audit and unanswerable check; the audit
  records the frozen prompts hash.
- **S11:** ledger records failed and `cancelled` runs; a stopped run is never recorded as success. S11
  adds the `events.jsonl` sink and run-level events on the S09 vocabulary, and builds the ledger from
  `LlmCallFinished` (ADR 0016), and closes the S09 spend gap on re-raised client errors (backlog A14).
- **S12:** the verifier agent subclasses `BaseLlmAgent`; map `llm.*` errors (including
  `llm.prompt_filtered`) to `FailureKind`; revisit Claude's `max_output_tokens=8192` budget.
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
uv run bio-claim-check run "Does OS-912 slow cognitive decline?" --fake
uv run bio-claim-check corpus verify
gh run list --limit 3
```
