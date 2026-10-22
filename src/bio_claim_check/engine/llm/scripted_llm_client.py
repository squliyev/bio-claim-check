"""[RING:engine/llm] A client that returns canned completions in order: for tests and the contract suite.

Why: the engine must be exercised end to end before any provider SDK exists (S09), deterministically.
A scripted entry may also be an exception, raised in its turn, so typed provider failures (transport,
prompt filter) can be exercised without a provider.
Must not: look at the request to choose an answer (it records requests so tests can).
"""

from collections.abc import Sequence
from typing import override

from bio_claim_check.common.errors import BccError
from bio_claim_check.engine.llm.base_llm_client import BaseLlmClient
from bio_claim_check.engine.llm.messages import LlmRequest, LlmResponse


class ScriptedLlmClient(BaseLlmClient):
    """Returns (or raises) `responses` one by one; raises `LookupError` when they run out."""

    def __init__(self, responses: Sequence[LlmResponse | BccError]) -> None:
        self._responses = tuple(responses)
        self.requests: list[LlmRequest] = []

    @override
    def complete(self, request: LlmRequest) -> LlmResponse:
        if len(self.requests) >= len(self._responses):
            raise LookupError(f"scripted client has only {len(self._responses)} response(s)")
        self.requests.append(request)
        scripted = self._responses[len(self.requests) - 1]
        if isinstance(scripted, BccError):
            raise scripted
        return scripted
