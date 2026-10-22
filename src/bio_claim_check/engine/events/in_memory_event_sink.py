"""[RING:engine/events] Keeps events in a list, in order: for tests and for `llm ping`'s summary.

Why: a caller that needs to read events back (assertions, a ping table) should not parse log lines.
Must not: be used where events must survive the process (S11 writes `events.jsonl`).

No LLM is involved in this module.
"""

from typing import override

from bio_claim_check.engine.events.base_event_sink import BaseEventSink
from bio_claim_check.engine.events.pipeline_event import PipelineEvent


class InMemoryEventSink(BaseEventSink):
    def __init__(self) -> None:
        self._events: list[PipelineEvent] = []

    @override
    def emit(self, event: PipelineEvent) -> None:
        self._events.append(event)

    @property
    def events(self) -> tuple[PipelineEvent, ...]:
        return tuple(self._events)
