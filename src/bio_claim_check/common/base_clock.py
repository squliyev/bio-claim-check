"""[RING:common] The clock port: the only way production code learns the time.

Why: pipeline events (ADR 0016) carry a timestamp, but canonical artifacts must be byte-identical
(I29), so time is injected, never read: tests and replays pass a `ScriptedClock`, `app` passes the one
`SystemClock`. It lives in `common` (not `engine`, as ADR 0002 first sketched) because the `[LEAF]`
events package, which stamps events, may import only `common`.
Must not: be read by code that produces a canonical artifact or a cache key.

No LLM is involved in this module.
"""

from abc import ABC, abstractmethod
from datetime import datetime


class BaseClock(ABC):
    """Tells the time; implemented as `<kind>_clock.py` beside this module."""

    @abstractmethod
    def now(self) -> datetime:
        """The current time, timezone-aware, in UTC."""
