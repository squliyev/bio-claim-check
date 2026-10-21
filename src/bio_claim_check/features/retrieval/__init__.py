"""[RING:features/retrieval] Find and normalise the abstracts an answer may cite.

Does: own the ``BaseLiteratureSource`` port and its backends (in-memory and Europe PMC, each
beside the base) and turn search hits into cleaned, citable abstracts.
Does not: rank papers by any judgement of quality.
"""
