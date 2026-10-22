"""[RING:engine/agent] The agent base every LLM agent extends (S09, ADR 0015).

Why: the answerer (S10), the verifier (S12) and the trap generator (S13) all render a prompt, build a
request from a model spec, run it through `LlmRunner` and report what happened. Doing that once, here,
keeps every agent to a declaration (name, prompt, output) and one method (`variables`).
Must not: import features (contract `engine-is-feature-agnostic`), hold domain prompt text, or call a
provider directly (the runner does, through the injected client). No `__init__` re-exports.
Contents: `base_llm_agent.py` (`[EXTENSION POINT]`), `agent_result.py`, `errors.py` and
`ping_llm_agent.py`, the feature-agnostic connectivity probe behind `llm ping`.
"""
