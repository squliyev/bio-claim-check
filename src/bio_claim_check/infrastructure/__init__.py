"""[RING:infrastructure] Tiny, generic, feature-agnostic transport: publish bytes, parse YAML, read text.

Why: domain backends live beside the base they implement (ADR 0007), so this ring holds only what any
feature could reuse and no feature owns. It imports `common` and drivers only (contract
`infrastructure-holds-only-transport`); the app composes it with pure feature code.
Must not: import features or engine, or make any domain decision.

No LLM is involved in this package.
"""
