"""Every event sink accepts every event type and keeps emission order (ADR 0016)."""

import json
import logging
from collections.abc import Callable

import pytest

from bio_claim_check.engine.events.base_event_sink import BaseEventSink
from bio_claim_check.engine.events.in_memory_event_sink import InMemoryEventSink
from bio_claim_check.engine.events.jsonl_event_sink import JsonlEventSink
from bio_claim_check.engine.events.logging_event_sink import LOGGER, LoggingEventSink
from bio_claim_check.engine.events.tee_event_sink import TeeEventSink
from tests.support.events import one_of_each

pytestmark = pytest.mark.contract

IMPLEMENTATIONS: tuple[type[BaseEventSink], ...] = (
    InMemoryEventSink,
    LoggingEventSink,
    JsonlEventSink,
    TeeEventSink,
)


class _Lines(JsonlEventSink):
    def __init__(self) -> None:
        self.lines: list[bytes] = []
        super().__init__(self.lines.append)


class _Tee(TeeEventSink):
    """Memory, then a line file: what a run records into; both copies must agree."""

    def __init__(self) -> None:
        self.memory = InMemoryEventSink()
        self.file = _Lines()
        super().__init__(self.memory, self.file)


def _read_back(sink: BaseEventSink, caplog: pytest.LogCaptureFixture) -> list[str]:
    if isinstance(sink, InMemoryEventSink):
        return [e.type for e in sink.events]
    if isinstance(sink, _Lines):
        return [json.loads(line)["type"] for line in sink.lines]
    if isinstance(sink, _Tee):
        memory, file = _read_back(sink.memory, caplog), _read_back(sink.file, caplog)
        assert memory == file
        return memory
    return [r.getMessage() for r in caplog.records if r.name == LOGGER]


BUILD: dict[type[BaseEventSink], Callable[[], BaseEventSink]] = {
    InMemoryEventSink: InMemoryEventSink,
    LoggingEventSink: LoggingEventSink,
    JsonlEventSink: _Lines,
    TeeEventSink: _Tee,
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
