"""[RING:engine/llm] The LLM port: one request in, one completion out.

Why: every provider, the cache and the scripted client are interchangeable behind this one method, and
the shared contract suite (`tests/contract/test_llm_client_contract.py`) holds them to one behaviour.
Must not: validate the output's meaning, retry for semantics, or repair (the runner does that).
"""

from abc import ABC, abstractmethod

from bio_claim_check.engine.llm.messages import LlmRequest, LlmResponse


class BaseLlmClient(ABC):
    """A source of completions."""

    @abstractmethod
    def complete(self, request: LlmRequest) -> LlmResponse:
        """Return the completion for `request`.

        Args:
            request: what the provider sees (plus `repeat_idx`, which only separates cache entries).

        Returns:
            The provider's text, measured usage and normalised finish reason. A truncated or filtered
            completion is returned, not raised: the runner decides what it means.

        Raises:
            LookupError: a scripted or replaying client has no answer for the request.
        """
