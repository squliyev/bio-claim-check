"""[RING:features/traps] Plant known misreadings to measure what a verifier catches (S13, ADR 0022).

Does: sample eligible dev sources, gate drafted (parent, trap) pairs, derive rule-floor traps, build and
read the author's audit sheet, and count verifier outcomes per kind.
Does not: leak trap kind, parent id or any metadata into what the verifier sees (the verifier receives a
claim's text only, I69), read files, or touch the test split (I78).
"""
