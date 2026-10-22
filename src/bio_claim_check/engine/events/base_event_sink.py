"""[RING:engine/events] The event sink port: where emitted events go.

Why: the runner, backends and agents emit events without knowing whether they are kept in memory
(tests, `llm ping`), logged (live diagnostics) or written to `events.jsonl` (S11).
Must not: transform or drop events, or raise on a valid event.

No LLM is involved in this module.
"""

from abc import ABC, abstractmethod

from bio_claim_check.engine.events.pipeline_event import PipelineEvent


class BaseEventSink(ABC):
    """Receives events in emission order; implemented as `<kind>_event_sink.py` beside this module."""

    @abstractmethod
    def emit(self, event: PipelineEvent) -> None: ...
