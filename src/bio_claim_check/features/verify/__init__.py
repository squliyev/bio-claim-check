"""[RING:features/verify] Judge one claim against only the abstract(s) it cites.

Does: own the ``BaseVerifier`` port and its backends (scripted now, the LLM verifier in S12, each
beside the base); keep the LLM's semantic label and the code-checked evidence status as two separate
axes.
Does not: see the question, other claims, trap metadata or any outside source (context isolation).
"""
