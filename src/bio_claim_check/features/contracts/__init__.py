"""[RING:features/contracts] Shared domain vocabulary: the only module every slice may import.

Does: hold the frozen pydantic models that cross slice boundaries (claims, verdicts, rule packs) and
the pure rules derived from them: the disposition table and worst-case claim aggregation (ADR 0006).
Keeping those rules next to the models means every slice reads the same pre-registered definition.
Does not: perform I/O, call an LLM or import any slice (import-linter contract
``contracts-do-not-depend-on-slices``). If two slices need to share behaviour beyond these derived
rules, it lives in the use case that composes them (``app.usecases``), not here.

No LLM is involved in this package.
"""
