# Handoff: how to continue this project

**Read this first** if you are a new agent or contributor picking up the work. Then read
[AGENTS.md](../AGENTS.md) (the rules), [roadmap.md](roadmap.md) (the plan) and the latest
`docs/dev-log/Sxx.md` (what just happened). Internal reference notes used for planning are kept outside
the repo; ask the maintainer for the rows relevant to your session.

## 1. Where things stand

- Done: S01, S02, S02b, S03, S04, S05, S05b, S06, S07a, the rule audit, S07b, S08, S08b.
  CI is green on `main`.
- **Next session: S09, provider adapters** (section 4).
- Next free ids: invariant **I52**, ADR **0014**.
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

## 4. Next: S09 — provider adapters

**Goal:** real LLM calls behind the existing `BaseLlmClient`, with honest usage, typed failures and
offline contract tests on recorded fixtures.

**Planned files (to be confirmed in the plan):**
- `engine/llm/openai_llm_client.py`: Azure AI Foundry `/openai/v1` surface (gpt-6.1-sol, Kimi-K2.6-1),
  strict `json_schema` structured output. Probe Kimi's structured-output support and record it. Optional:
  Ollama pinned by digest.
- `engine/llm/anthropic_llm_client.py`: `AnthropicFoundry` (claude-opus-4-8), structured output by
  **forced tool use**, system prompt as the separate `system` parameter.
- `bio-claim-check llm ping` (live check of every deployment) and **ADR 0014** (pinned model ids and the
  structured-output support matrix).

**Bindings from earlier sessions (must hold):**
- Usage normalisation: reasoning ⊆ output, cached input ⊆ input; `reasoning_tokens` is `None` when the
  provider does not report it (I51). One test per raw usage shape of each provider.
- Truncation and content filtering come back as `finish_reason` (`length`, `content_filter`); filtered
  items are counted, never hidden (I44).
- Reasoning content is **never replayed**. Model identity (provider, deployment, `model_version`) is in
  the cache key (I46).
- `model_version` is pinned and **supplied by the maintainer**. No invented model ids, limits or prices;
  unknown price means "unpriced" (I45).
- Recorded fixtures are scrubbed: no endpoints, keys, personal data or abstract text beyond fictional
  content.
- Request shapes come from the official SDK documentation and our own recordings.
- Drivers (`openai`, `anthropic`) may be imported only by backend modules; classify them in
  `tests/arch/test_dependency_policy.py`. Every backend runs the shared LLM client contract suite.

**Open questions for the maintainer (ask before planning details):**
1. The pinned `model_version` for each deployment.
2. Scope: include Ollama and the Anthropic API directly, or only the Foundry deployments?
3. Credentials: does the Anthropic deployment use a separate Foundry endpoint/key?
4. Fixtures: scrubbed live recordings, or hand-written from the documented shapes?
5. Prices: supply them now, or leave them `None` (shown as "unpriced")?

**Exit:** live `llm ping` passes for every deployment; the contract suite passes offline on recorded
fixtures for each provider; `make verify` and CI green.

## 5. Engine contracts you build on (S08, S08b)

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
- **S11:** ledger records failed and `cancelled` runs; a stopped run is never recorded as success.
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
make live            # opt-in live tests (needs BCC_CONTACT_EMAIL)
uv run bio-claim-check run "Does OS-912 slow cognitive decline?" --fake
uv run bio-claim-check corpus verify
gh run list --limit 3
```
