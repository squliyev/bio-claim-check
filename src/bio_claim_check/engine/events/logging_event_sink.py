"""[RING:engine/events] Writes each event as one log record (INFO, logger `bio_claim_check.events`).

Why: live diagnostics (S09's `llm ping`, live tests) need events on stderr before S11 adds the
`events.jsonl` writer. The event's fields go in `extra=` under `pipeline_event`, so the app's
formatters redact by key as for every other record (I50); the message is the event type.
Must not: format content into the message string, or write to stdout.

No LLM is involved in this module.
"""

import logging
from typing import Final, override

from bio_claim_check.engine.events.base_event_sink import BaseEventSink
from bio_claim_check.engine.events.pipeline_event import PipelineEvent

LOGGER: Final = "bio_claim_check.events"


class LoggingEventSink(BaseEventSink):
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(LOGGER)

    @override
    def emit(self, event: PipelineEvent) -> None:
        self._logger.info(event.type, extra={"pipeline_event": event.model_dump(mode="json")})
