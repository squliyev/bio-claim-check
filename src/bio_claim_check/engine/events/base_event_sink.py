"""[RING:engine/events] The event sink port: where emitted events go.

Why: the runner, backends and agents emit events without knowing whether they are kept in memory
(tests, `llm ping`), logged (live diagnostics) or written to a run's trace file (S11, ADR 0018).
Must not: transform or drop events. An in-memory or logging sink never raises on a valid event; a
persistent sink may fail to write, and then raises only `EventWriteError` (`engine/events/errors.py`), so
callers can tell a lost trace line from a failure of the work being traced (S11 amended this from "must
not raise").

No LLM is involved in this module.
"""

from abc import ABC, abstractmethod

from bio_claim_check.engine.events.pipeline_event import PipelineEvent


class BaseEventSink(ABC):
    """Receives events in emission order; implemented as `<kind>_event_sink.py` beside this module."""

    @abstractmethod
    def emit(self, event: PipelineEvent) -> None: ...
