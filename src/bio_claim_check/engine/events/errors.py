"""[RING:engine/events] The typed failure of a persistent event sink.

Why: a trace file can fail to open, write or close (S11, ADR 0018). Callers must tell a lost trace line
from a failure of the work being traced, so a persistent sink raises only this error, and the runner and
`stage()` re-raise it untouched instead of recording it as a failed call or stage.
Must not: carry event content (it may quote input).

No LLM is involved in this module.
"""

from bio_claim_check.common.errors import BccError


class EventWriteError(BccError):
    """A persistent sink could not write an event (or open or close its file)."""

    code = "events.write"
