"""[RING:common] A deterministic clock for tests and replays.

Why: event timestamps must be reproducible wherever a test or a replay compares them. Each `now()`
returns `start + n * step` for the n-th call (n from 0), so the order of events is visible in their time.
Must not: read the wall clock.

No LLM is involved in this module.
"""

from datetime import UTC, datetime, timedelta
from typing import override

from bio_claim_check.common.base_clock import BaseClock


class ScriptedClock(BaseClock):
    """Starts at `start` (UTC-aware) and advances by `step` on every call."""

    def __init__(self, start: datetime, step: timedelta = timedelta(0)) -> None:
        if start.utcoffset() != timedelta(0):
            raise ValueError("start must be timezone-aware UTC")
        if step < timedelta(0):
            raise ValueError("a clock never goes backwards")
        self._next = start.astimezone(UTC)
        self._step = step

    @override
    def now(self) -> datetime:
        current = self._next
        self._next = current + self._step
        return current
