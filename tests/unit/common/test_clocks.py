from datetime import UTC, datetime, timedelta, timezone

import pytest

from bio_claim_check.common.scripted_clock import ScriptedClock

START = datetime(2026, 1, 1, tzinfo=UTC)


def test_scripted_clock_steps_from_start() -> None:
    clock = ScriptedClock(START, timedelta(seconds=2))
    assert [clock.now(), clock.now()] == [START, START + timedelta(seconds=2)]


def test_scripted_clock_defaults_to_a_fixed_time() -> None:
    clock = ScriptedClock(START)
    assert clock.now() == clock.now() == START


def test_scripted_clock_normalises_to_utc_tzinfo() -> None:
    assert ScriptedClock(START.replace(tzinfo=timezone(timedelta(0)))).now().tzinfo is UTC


@pytest.mark.parametrize(
    ("start", "step"),
    [
        (datetime(2026, 1, 1), timedelta(0)),
        (datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))), timedelta(0)),
        (START, timedelta(seconds=-1)),
    ],
)
def test_scripted_clock_rejects_bad_input(start: datetime, step: timedelta) -> None:
    with pytest.raises(ValueError, match=r"UTC|backwards"):
        ScriptedClock(start, step)
