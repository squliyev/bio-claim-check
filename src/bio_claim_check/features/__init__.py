"""[RING:features] Pure domain, one vertical slice per sub-package.

Slices never import each other; the shared vocabulary lives in ``features.contracts``.
Domain ports (for example ``LiteratureSource``) are owned by the slice that consumes them.
"""
