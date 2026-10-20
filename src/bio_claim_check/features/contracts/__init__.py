"""[RING:features/contracts] Shared domain vocabulary: the only module every slice may import.

Does: hold the frozen pydantic models that cross slice boundaries (claims, papers, verdicts; S04).
Does not: contain behaviour or import any slice (import-linter contract
``contracts-do-not-depend-on-slices``). If two slices need to share logic, that logic lives in the
use case that composes them (``app.usecases``), not here.
"""
