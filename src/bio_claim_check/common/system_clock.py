"""[RING:common] The one real clock: the only module in `src` allowed to read the wall clock.

Why: something has to tell the real time for live runs' event timestamps; making that exactly one
named module (a single ruff `TID251` per-file exemption, pinned by a test) keeps I29 checkable instead
of scattering exemptions (ADR 0016 amends ADR 0007 §8). Only `app` constructs it.
Must not: be used for anything canonical (artifacts, cache keys, hashes), or be constructed outside `app`.

No LLM is involved in this module.
"""

from datetime import UTC, datetime
from typing import override

from bio_claim_check.common.base_clock import BaseClock


class SystemClock(BaseClock):
    """The wall clock, in UTC."""

    @override
    def now(self) -> datetime:
        return datetime.now(UTC)
