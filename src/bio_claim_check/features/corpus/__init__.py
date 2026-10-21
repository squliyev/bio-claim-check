"""[RING:features/corpus] Builds the evaluation corpus: the sieve, the cluster split and the canonical bytes.

Does: decide which retrieved abstracts are trap candidates (sieve v1, from MeSH, publication types and
fixed sentence patterns), join papers that report the same trial into clusters, assign each cluster to
dev or test from a public salted hash, and serialise the result byte-for-byte reproducibly (ADR 0010).
Does not: fetch (the use case passes papers in), mutate claims into traps (``features.traps``), or decide
that a candidate really is overstated; a human audit confirms candidates later (S07b).

No LLM is involved in this slice; import-linter contract ``no-llm-in-deterministic-code`` enforces it
(ADR 0003).
"""
