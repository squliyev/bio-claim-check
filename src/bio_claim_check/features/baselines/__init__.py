"""[RING:features/baselines] Simple verifiers that any LLM verifier must beat (S14).

Does: implement the same ``Verifier`` behaviour with always-flag, MeSH-cue and NLI baselines.
Does not: import ``features.verify``; baselines satisfy the shared contract suite, not a base class.
"""
