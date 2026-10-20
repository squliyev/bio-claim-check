"""[RING:features/annotate] Agreement between annotators: raw agreement, confusion, Cohen's kappa (S18).

Why a separate module: agreement numbers are reported in the write-up, so they must be deterministic
and guarded against degenerate cases (n = 0, a single class).

No LLM is involved in this module; import-linter contract ``no-llm-in-deterministic-code`` enforces it
(ADR 0003).
"""
