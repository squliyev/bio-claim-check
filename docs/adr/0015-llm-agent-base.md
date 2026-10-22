# ADR 0015 — One base for every LLM agent

- **Status:** Accepted
- **Date:** 2026-10-22
- **Supersedes / Extends:** Extends 0012 (one runner) and 0007 (extension points)
- **Related:** 0004, 0016
- **Enforced by:** `tests/unit/engine/test_base_llm_agent.py` · `tests/contract/test_llm_agent_contract.py` · `tests/arch/test_port_guards.py::test_core_has_no_import_time_registries` · import-linter `engine-is-feature-agnostic`

## Context

The answerer (S10), the verifier (S12) and the trap generator (S13) all do the same thing: render a prompt,
build a request from a model spec, run it through `LlmRunner`, and keep the provenance. Written three times,
the copies drift: one forgets the `PromptRef`, one keeps per-call state, one wraps the runner differently.

## Decision

1. `engine/agent/base_llm_agent.py` holds `BaseLlmAgent[P, T]`, an `[EXTENSION POINT]`. A subclass, named
   `<what>_llm_agent.py` and living in its feature (or in `engine/agent` when feature-agnostic), declares
   three class attributes: `name` (`^[a-z][a-z0-9_]*$`), `prompt: PromptTemplate` and `output` (a pydantic
   model), and writes one method, `variables(payload)`.
2. Declarations are checked when the agent is **constructed**, not at class creation, because core has no
   import-time hooks (I28). A missing or invalid attribute, or an override of `run` anywhere in the
   hierarchy, raises `agent.declaration`.
3. `run(payload, *, repeat_idx, params)` is final. It renders the prompt, builds the request with
   `request_for` (spec params merged with call params) carrying `prompt.ref()`, and delegates to the runner
   built in `__init__`. It returns `AgentResult(agent, output, invocation)`. The agent keeps no per-call state.
4. Processors stay injected by `app`, in the caller's order (ADR 0012). Features **compose** an agent (a
   `BaseVerifier` implementation holds a `VerifyLlmAgent`); they do not inherit from both.
5. The agent wraps each run in `StageStarted` / `StageFinished` / `StageFailed` (stage = agent name) and
   labels the runner's LLM events with its name (ADR 0016).
6. Every agent runs the shared `tests/contract/test_llm_agent_contract.py` (an `IMPLEMENTATIONS` list with
   one case per agent). `engine/agent/ping_llm_agent.py` (`PingLlmAgent`, fictional fixed text) is the first,
   used by `bio-claim-check llm ping`.

## Consequences

- **Positive:** a new agent is three attributes and one method; provenance and events cannot be forgotten;
  the base was proven live on both providers before S10.
- **Negative / costs:** a declaration mistake shows at first construction rather than at import; the contract
  suite needs one case per agent.
- **Follow-ups (binding):** S10 `AnswerLlmAgent`, S12 the verifier agent, S13 the trap agent all subclass
  `BaseLlmAgent` and join the agent contract suite.
