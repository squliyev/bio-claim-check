"""Usage subsets, exact Decimal cost and honest spend (I45)."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from tests.support.llm import PRICE

from bio_claim_check.engine.llm.usage import Price, Spend, Usage, cost

pytestmark = pytest.mark.unit


def test_defaults_are_zero_and_keyword_only() -> None:
    assert Usage() == Usage(input_tokens=0, output_tokens=0, reasoning_tokens=0, cached_input_tokens=0)
    assert Spend().usage == Usage()
    assert Spend().cost == Decimal(0)


@pytest.mark.parametrize(
    "fields",
    [
        {"output_tokens": 3, "reasoning_tokens": 4},
        {"input_tokens": 3, "cached_input_tokens": 4},
        {"input_tokens": -1},
        {"input_tokens": True},
        {"input_tokens": 1.0},
    ],
)
def test_impossible_usage_is_rejected(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Usage.model_validate(fields)


def test_usage_adds_fieldwise() -> None:
    a = Usage(input_tokens=10, output_tokens=5, reasoning_tokens=2, cached_input_tokens=4)
    b = Usage(input_tokens=1, output_tokens=2, reasoning_tokens=1, cached_input_tokens=1)
    assert a + b == Usage(input_tokens=11, output_tokens=7, reasoning_tokens=3, cached_input_tokens=5)


def test_cost_is_exact_and_charges_cached_input_at_its_own_rate() -> None:
    usage = Usage(input_tokens=1_000, output_tokens=200, reasoning_tokens=150, cached_input_tokens=400)
    # 600 * 2.50 + 400 * 1.25 + 200 * 10 = 1500 + 500 + 2000 = 4000 per million → 0.004
    assert cost(usage, PRICE) == Decimal("0.004")


def test_missing_cached_rate_falls_back_to_the_input_rate() -> None:
    price = Price(input_per_mtok=Decimal(3), output_per_mtok=Decimal(0), as_of=date(2026, 1, 1), source="s")
    assert cost(Usage(input_tokens=1_000_000, cached_input_tokens=999_999), price) == Decimal(3)


def test_unpriced_is_none_never_zero() -> None:
    assert cost(Usage(input_tokens=5), None) is None


@pytest.mark.parametrize("value", [1.5, True, "-1", "NaN", "Infinity"])
def test_prices_must_be_finite_non_negative_decimals(value: object) -> None:
    with pytest.raises(ValidationError):
        Price.model_validate(
            {"input_per_mtok": value, "output_per_mtok": "1", "as_of": "2026-01-01", "source": "s"}
        )


def test_money_serialises_as_a_decimal_string() -> None:
    assert '"input_per_mtok":"2.50"' in PRICE.model_dump_json()
    assert Price.model_validate_json(PRICE.model_dump_json()) == PRICE


def test_spend_counts_live_calls_and_their_cost() -> None:
    paid = Usage(input_tokens=1_000_000, output_tokens=0)
    spend = Spend().record(paid=paid, usage=paid, price=PRICE).record(paid=paid, usage=paid, price=PRICE)
    assert (spend.calls, spend.cache_hits, spend.cost) == (2, 0, Decimal("5.00"))
    assert spend.usage == paid + paid


def test_a_cache_hit_costs_nothing_but_is_counted_as_replayed() -> None:
    used = Usage(input_tokens=7, output_tokens=3)
    spend = Spend().record(paid=None, usage=used, price=PRICE)
    assert (spend.calls, spend.cache_hits, spend.cost, spend.usage) == (0, 1, Decimal(0), Usage())
    assert spend.replayed_usage == used


def test_one_unpriced_live_call_makes_the_whole_cost_unknown_for_good() -> None:
    used = Usage(input_tokens=7)
    spend = Spend().record(paid=used, usage=used, price=None)
    assert spend.cost is None
    spend = spend.record(paid=used, usage=used, price=PRICE).record(paid=None, usage=used, price=PRICE)
    assert spend.cost is None
    assert spend.calls == 2
