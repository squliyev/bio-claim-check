"""[RING:engine/events] Sends each event to two sinks in order: the first, then the second.

Why: a run keeps its events in memory first (the ledger and manifest fold that copy) and then writes them
to the trace file. If the file write fails, the memory copy already holds the event, so known usage is
never lost (ADR 0018, I67).
Must not: swallow a failure, or fan out to more than two sinks (no caller needs it).

No LLM is involved in this module.
"""

from typing import override

from bio_claim_check.engine.events.base_event_sink import BaseEventSink
from bio_claim_check.engine.events.pipeline_event import PipelineEvent


class TeeEventSink(BaseEventSink):
    def __init__(self, first: BaseEventSink, second: BaseEventSink) -> None:
        self._first = first
        self._second = second

    @override
    def emit(self, event: PipelineEvent) -> None:
        self._first.emit(event)
        self._second.emit(event)
