"""[RING:engine/cache] Content-addressed response cache: the base, its implementations and the policy.

Does: store raw response bytes under a key derived from every input that shapes the request, so a
replay reads exactly what a live run read (ADR 0009). `read-only` fails closed on a miss.
Does not: know what is cached (papers, LLM outputs): callers build the key and parse the bytes.
This package never re-exports the SQLite backend, so importing it loads no driver (ADR 0007).
No LLM is involved in this module: it stores LLM outputs later but never calls a model.
"""
