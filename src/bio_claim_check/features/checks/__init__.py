"""[RING:features/checks] Deterministic checks on an agent answer.

Does: flag citations to papers that were never retrieved and verify that quoted evidence occurs in the
cited abstract (S10).
Does not: judge meaning. Whether a claim is *supported* is decided in ``features.verify``.

No LLM is involved in this slice; import-linter contract ``no-llm-in-deterministic-code`` enforces it
(ADR 0003).
"""
