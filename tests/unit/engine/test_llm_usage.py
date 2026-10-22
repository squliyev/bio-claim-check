"""Usage subsets, exact Decimal cost, honest spend (I45) and unreported reasoning tokens (I51)."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from tests.support.llm import PRICE

from bio_claim_check.engine.llm.usage import Price, Spend, Usage, cost

pytestmark = pytest.mark.unit


def test_defaults_are_zero_and_reasoning_is_unreported() -> None:
    assert Usage() == Usage(input_tokens=0, output_tokens=0, reasoning_tokens=None, cached_input_tokens=0)
    assert Usage.zero() == Usage(reasoning_tokens=0)
    assert Spend().usage == Spend().replayed_usage == Usage.zero()
    assert Spend().cost == Decimal(0)


@pytest.mark.parametrize(
    ("reasoning", "expected"),
    [(None, None), (0, 0), (5, 5), (20, 20)],
    ids=["not-reported", "reported-zero", "positive", "all-of-output"],
)
def test_reasoning_is_kept_exactly_as_reported(reasoning: int | None, expected: int | None) -> None:
    assert Usage(output_tokens=20, reasoning_tokens=reasoning).reasoning_tokens == expected


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [(None, None, None), (None, 3, None), (3, None, None), (0, 3, 3), (2, 3, 5)],
)
def test_a_sum_with_an_unreported_side_is_unknown(
    left: int | None, right: int | None, expected: int | None
) -> None:
    total = Usage(output_tokens=9, reasoning_tokens=left) + Usage(output_tokens=9, reasoning_tokens=right)
    assert total.reasoning_tokens == expected
    assert total.output_tokens == 18


def test_spend_reasoning_turns_unknown_after_one_non_reporting_call() -> None:
    told = Usage(input_tokens=1, output_tokens=4, reasoning_tokens=2)
    silent = Usage(input_tokens=1, output_tokens=4)
    spend = Spend().record(paid=told, usage=told, price=PRICE)
    assert spend.usage.reasoning_tokens == 2
    assert spend.record(paid=silent, usage=silent, price=PRICE).usage.reasoning_tokens is None


def test_unreported_reasoning_does_not_change_the_cost() -> None:
    reported = Usage(input_tokens=1_000, output_tokens=200, reasoning_tokens=0)
    silent = Usage(input_tokens=1_000, output_tokens=200)
    assert cost(reported, PRICE) == cost(silent, PRICE) == Decimal("0.0045")


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
    assert (spend.calls, spend.cache_hits, spend.cost, spend.usage) == (0, 1, Decimal(0), Usage.zero())
    assert spend.replayed_usage == used


def test_one_unpriced_live_call_makes_the_whole_cost_unknown_for_good() -> None:
    used = Usage(input_tokens=7)
    spend = Spend().record(paid=used, usage=used, price=None)
    assert spend.cost is None
    spend = spend.record(paid=used, usage=used, price=PRICE).record(paid=None, usage=used, price=PRICE)
    assert spend.cost is None
    assert spend.calls == 2


def test_an_unmeasured_call_adds_no_tokens_and_makes_cost_unknown() -> None:
    spent = Spend().record_unmeasured()
    assert (spent.calls, spent.unmeasured_calls, spent.cost, spent.usage) == (0, 1, None, Usage.zero())
    after = spent.record(paid=Usage(input_tokens=1), usage=Usage(input_tokens=1), price=None)
    assert after.unmeasured_calls == 1
    hit = spent.record(paid=None, usage=Usage(input_tokens=1), price=None)
    assert (hit.unmeasured_calls, hit.cache_hits) == (1, 1)
