"""[RING:engine/llm] A cap on live LLM calls per command, refused before the call is made.

Why: a bug or a long dev loop must not spend without bound. The budgeted client wraps the *live*
client inside the cache (`CachingLlmClient(BudgetedLlmClient(live, budget), ...)`), so cache hits never
touch it. One `CallBudget` is shared by every budgeted client of a command, so the cap holds across
models (ADR 0018, I68). It counts logical calls; a backend's transport retries inside one call are
bounded by its transport policy and shown in the ledger as `transport_retries`.
Must not: count cache hits, or call the inner client once the budget is spent.
"""

from typing import override

from bio_claim_check.engine.llm.base_llm_client import BaseLlmClient
from bio_claim_check.engine.llm.errors import LlmBudgetExceededError
from bio_claim_check.engine.llm.messages import LlmRequest, LlmResponse


class CallBudget:
    """How many live calls a command may still make."""

    def __init__(self, max_calls: int) -> None:
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError(f"max_calls must be an int ≥ 1, got {max_calls!r}")
        self._max = max_calls
        self._used = 0

    @property
    def used(self) -> int:
        return self._used

    def take(self) -> None:
        """Count one call, or raise before it if the budget is spent."""
        if self._used >= self._max:
            raise LlmBudgetExceededError(
                f"refused live LLM call {self._used + 1}: the limit is {self._max} per command "
                "(BCC_MAX_LIVE_LLM_CALLS)"
            )
        self._used += 1


class BudgetedLlmClient(BaseLlmClient):
    def __init__(self, inner: BaseLlmClient, budget: CallBudget) -> None:
        self._inner = inner
        self._budget = budget

    @override
    def complete(self, request: LlmRequest) -> LlmResponse:
        self._budget.take()
        return self._inner.complete(request)
