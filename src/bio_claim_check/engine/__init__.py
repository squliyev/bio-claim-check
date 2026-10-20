"""[RING:engine] The feature-agnostic core runtime: LLM client, cache, prompts, pipeline, events, ledger.

Features use the engine; the engine never uses features (contract `engine-is-feature-agnostic`). Its
bases are generic over their payload, so it needs no claim, paper or verdict type: features extend its
bases and `app` wires them in. If engine code seems to need a domain type, the type is generic and
belongs in `common`, or the logic belongs in a feature (ADR 0007).
Must not: import features (including `features.contracts`), infrastructure or app.
"""
