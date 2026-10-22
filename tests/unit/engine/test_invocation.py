"""Invocation is a frozen value with an empty, zero-cost start."""

import dataclasses
from decimal import Decimal

import pytest
from tests.support.llm import request

from bio_claim_check.engine.pipeline.invocation import Invocation

pytestmark = pytest.mark.unit


def test_defaults_are_empty_and_free() -> None:
    inv = Invocation(payload=1, request=request())
    assert inv.responses == ()
    assert inv.spend.calls == 0
    assert inv.spend.cost == Decimal(0)


def test_frozen() -> None:
    inv = Invocation(payload=1, request=request())
    with pytest.raises(dataclasses.FrozenInstanceError):
        inv.payload = 2  # pyright: ignore[reportAttributeAccessIssue] - assigning to a frozen field on purpose
