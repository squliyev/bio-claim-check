"""[RING:features/bench] Statistics for the benchmark: bootstrap, paired intervals, McNemar (S16).

Why a separate module: these functions must be reproducible to the last digit, so they are pure,
deterministic and tested against reference values.

No LLM is involved in this module; import-linter contract ``no-llm-in-deterministic-code`` enforces it
(ADR 0003).
"""
