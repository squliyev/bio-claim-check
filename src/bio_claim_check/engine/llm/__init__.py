"""[RING:engine/llm] Provider-neutral LLM port and structured-call machinery (built in S08).

Does: define the ``LlmClient`` port, model catalogue, prompt rendering and validated structured calls.
Does not: know about claims, papers or labels; talk to a provider SDK directly (adapters do that).

Deterministic modules are forbidden from importing this package (import-linter contract
``no-llm-in-deterministic-code``, ADR 0003).
"""
