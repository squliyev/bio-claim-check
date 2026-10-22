"""Every event sink accepts every event type and keeps emission order (ADR 0016)."""

import logging
from collections.abc import Callable

import pytest

from bio_claim_check.engine.events.base_event_sink import BaseEventSink
from bio_claim_check.engine.events.in_memory_event_sink import InMemoryEventSink
from bio_claim_check.engine.events.logging_event_sink import LOGGER, LoggingEventSink
from tests.support.events import one_of_each

pytestmark = pytest.mark.contract

IMPLEMENTATIONS: tuple[type[BaseEventSink], ...] = (InMemoryEventSink, LoggingEventSink)


def _read_back(sink: BaseEventSink, caplog: pytest.LogCaptureFixture) -> list[str]:
    if isinstance(sink, InMemoryEventSink):
        return [e.type for e in sink.events]
    return [r.getMessage() for r in caplog.records if r.name == LOGGER]


BUILD: dict[type[BaseEventSink], Callable[[], BaseEventSink]] = {
    InMemoryEventSink: InMemoryEventSink,
    LoggingEventSink: LoggingEventSink,
}


@pytest.fixture(params=IMPLEMENTATIONS, ids=lambda c: c.__name__)
def sink(request: pytest.FixtureRequest) -> BaseEventSink:
    return BUILD[request.param]()


def test_accepts_every_event_type_in_order(sink: BaseEventSink, caplog: pytest.LogCaptureFixture) -> None:
    events = one_of_each()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        for event in events:
            sink.emit(event)
    assert _read_back(sink, caplog) == [e.type for e in events]
