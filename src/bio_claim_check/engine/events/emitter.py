"""[RING:engine/events] Stamps events with the injected clock's time and hands them to a sink.

Why: one place reads the time for events, so no emitter can reach for the wall clock, and every event
in a run shares one clock (a `ScriptedClock` makes event logs reproducible in tests).
Must not: buffer, reorder or drop events.

No LLM is involved in this module.
"""

from collections.abc import Callable
from datetime import datetime

from bio_claim_check.common.base_clock import BaseClock
from bio_claim_check.engine.events.base_event_sink import BaseEventSink
from bio_claim_check.engine.events.pipeline_event import PipelineEvent


class EventEmitter:
    """`emit(lambda at: SomeEvent(at=at, ...))`: the builder receives the time and returns the event."""

    def __init__(self, sink: BaseEventSink, clock: BaseClock) -> None:
        self._sink = sink
        self._clock = clock

    def emit[E: PipelineEvent](self, build: Callable[[datetime], E]) -> E:
        event = build(self._clock.now())
        self._sink.emit(event)
        return event
