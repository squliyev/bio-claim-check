"""Every clock tells timezone-aware UTC time that never goes backwards (ADR 0016)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from bio_claim_check.common.base_clock import BaseClock
from bio_claim_check.common.scripted_clock import ScriptedClock
from bio_claim_check.common.system_clock import SystemClock

pytestmark = pytest.mark.contract

IMPLEMENTATIONS: tuple[type[BaseClock], ...] = (ScriptedClock, SystemClock)
BUILD: dict[type[BaseClock], Callable[[], BaseClock]] = {
    ScriptedClock: lambda: ScriptedClock(datetime(2026, 1, 1, tzinfo=UTC), timedelta(seconds=1)),
    SystemClock: SystemClock,
}


@pytest.fixture(params=IMPLEMENTATIONS, ids=lambda cls: cls.__name__)
def clock(request: pytest.FixtureRequest) -> BaseClock:
    return BUILD[request.param]()


def test_now_is_utc_aware(clock: BaseClock) -> None:
    assert clock.now().utcoffset() == timedelta(0)


def test_now_never_goes_backwards(clock: BaseClock) -> None:
    first, second = clock.now(), clock.now()
    assert second >= first
