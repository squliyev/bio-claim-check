"""[RING:features/answer] Produce an answer whose every claim cites a retrieved abstract.

Does: run the Strict and Over-eager answer modes (S10) and refuse claims that are not
self-contained ("this drug", "these results").
Does not: use outside knowledge, or check its own claims; that is the verifier's job.
"""
