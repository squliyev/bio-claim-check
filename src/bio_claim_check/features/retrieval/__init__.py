"""[RING:features/retrieval] Find and normalise the abstracts an answer may cite.

Does: own the ``LiteratureSource`` port (S06) and turn search hits into cleaned, citable abstracts.
Does not: call Europe PMC directly (``infrastructure`` implements the port) or rank papers by any
judgement of quality.
"""
