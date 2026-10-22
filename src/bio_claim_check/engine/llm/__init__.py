"""[RING:engine/llm] Provider-neutral LLM port, request/response shapes, usage and cost (built in S08).

Does: define `BaseLlmClient` and its scripted and caching implementations, `LlmRequest`/`LlmResponse`,
the model catalogue, measured `Usage`, `Price`, `Spend` and the typed `LlmCallError`. Prompt templates
live in `engine/prompts`; the runner (order, repair) lives in `engine/pipeline`.
Does not: know about claims, papers or labels; talk to a provider SDK (S09 backends sit beside the base).

Deterministic modules are forbidden from importing this package (import-linter contract
``no-llm-in-deterministic-code``, ADR 0003).
"""
