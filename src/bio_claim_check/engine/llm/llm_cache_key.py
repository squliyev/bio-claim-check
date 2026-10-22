"""[RING:engine/llm] The LLM cache key: one hash over every request-shaping input (I43).

Why: the caching client stores responses under this key, and pipeline events carry it as
`request_hash`, so an event can be joined to its stored response. It moved out of
`caching_llm_client` (a backend module, which nothing else may import) unchanged.
Must not: include provenance-only fields (the prompt reference) or anything volatile.

Pure values: makes no provider call. (It is LLM vocabulary, so it does not carry the
ADR 0003 deterministic marker.)
"""

from typing import Final

from bio_claim_check.engine.cache.policy import cache_key
from bio_claim_check.engine.llm.messages import LlmRequest

NAMESPACE: Final = "llm.complete"
KEY_VERSION: Final = 1


def llm_cache_key(request: LlmRequest) -> str:
    return cache_key(NAMESPACE, KEY_VERSION, request.cache_payload())
