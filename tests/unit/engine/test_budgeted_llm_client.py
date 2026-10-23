"""I68: one shared budget caps live LLM calls per command, refused before the call; cache hits are free."""

import pytest
from tests.support.llm import request, response

from bio_claim_check.engine.cache.in_memory_cache import InMemoryCache
from bio_claim_check.engine.cache.policy import CacheMode
from bio_claim_check.engine.llm.budgeted_llm_client import BudgetedLlmClient, CallBudget
from bio_claim_check.engine.llm.caching_llm_client import CachingLlmClient
from bio_claim_check.engine.llm.errors import LlmBudgetExceededError
from bio_claim_check.engine.llm.scripted_llm_client import ScriptedLlmClient

pytestmark = pytest.mark.unit


def test_the_call_after_the_limit_is_refused_before_it_reaches_the_client() -> None:
    inner = ScriptedLlmClient([response(), response()])
    client = BudgetedLlmClient(inner, CallBudget(1))
    client.complete(request(repeat_idx=0))
    with pytest.raises(LlmBudgetExceededError, match="BCC_MAX_LIVE_LLM_CALLS"):
        client.complete(request(repeat_idx=1))
    assert len(inner.requests) == 1


def test_one_budget_is_shared_by_every_client_of_a_command() -> None:
    budget = CallBudget(2)
    a = BudgetedLlmClient(ScriptedLlmClient([response()]), budget)
    b = BudgetedLlmClient(ScriptedLlmClient([response(), response()]), budget)
    a.complete(request())
    b.complete(request())
    with pytest.raises(LlmBudgetExceededError):
        b.complete(request(repeat_idx=1))
    assert budget.used == 2


def test_cache_hits_do_not_spend_the_budget() -> None:
    cache = InMemoryCache()
    budget = CallBudget(1)
    client = CachingLlmClient(
        BudgetedLlmClient(ScriptedLlmClient([response()]), budget), cache, CacheMode.READ_WRITE
    )
    client.complete(request())
    assert client.complete(request()).cache_hit
    assert budget.used == 1


@pytest.mark.parametrize("bad", [0, -1, True, 1.0])
def test_a_budget_needs_a_positive_int(bad: int) -> None:
    with pytest.raises(ValueError, match="max_calls"):
        CallBudget(bad)
