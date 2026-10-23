"""[RING:engine/events] Writes each event as one compact JSON line through a line writer.

Why: a run's trace must survive a crash up to its last event, so each event is written (and the writer
flushes) as it is emitted (ADR 0018). The file itself is opened by the app's wiring; this sink only turns
events into lines, so `engine` does no file handling.
Must not: buffer, reorder or drop events, or raise anything but `EventWriteError` on a write failure.

No LLM is involved in this module.
"""

from collections.abc import Callable
from typing import override

from bio_claim_check.engine.events.base_event_sink import BaseEventSink
from bio_claim_check.engine.events.errors import EventWriteError
from bio_claim_check.engine.events.pipeline_event import PipelineEvent


def event_line(event: PipelineEvent) -> bytes:
    """One event as compact JSON in field order, without the newline."""
    return event.model_dump_json().encode("utf-8")


class JsonlEventSink(BaseEventSink):
    """`write_line` receives one line without its newline; an `OSError` becomes `EventWriteError`."""

    def __init__(self, write_line: Callable[[bytes], None]) -> None:
        self._write_line = write_line

    @override
    def emit(self, event: PipelineEvent) -> None:
        try:
            self._write_line(event_line(event))
        except OSError as err:
            raise EventWriteError(f"cannot write the trace: {err.strerror or err}") from err
