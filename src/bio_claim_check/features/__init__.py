"""[RING:features] Pure domain, one vertical slice per sub-package.

Slices never import each other; the shared vocabulary lives in ``features.contracts``.
Domain ports (for example ``BaseLiteratureSource``) are owned by the slice that consumes them; their
backends sit beside them (ADR 0007).
"""
