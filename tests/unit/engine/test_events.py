import logging
from typing import Literal, get_args, get_origin

import pytest
from pydantic import ValidationError
from tests.support.events import MODEL, T0, one_of_each, stepping_clock

from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.in_memory_event_sink import InMemoryEventSink
from bio_claim_check.engine.events.llm_events import LlmCallFinished, LlmRetryScheduled
from bio_claim_check.engine.events.logging_event_sink import LOGGER, LoggingEventSink
from bio_claim_check.engine.events.stage_events import StageFailed, StageFinished, StageStarted, is_terminal
from bio_claim_check.engine.llm.usage import Usage

pytestmark = pytest.mark.unit


def test_emitter_stamps_events_from_the_clock_in_order() -> None:
    sink = InMemoryEventSink()
    emitter = EventEmitter(sink, stepping_clock())
    first = emitter.emit(lambda at: StageStarted(at=at, stage="a"))
    second = emitter.emit(lambda at: StageFinished(at=at, stage="a"))
    assert sink.events == (first, second)
    assert second.at > first.at == T0


def test_terminal_events_close_a_stage() -> None:
    assert [is_terminal(e) for e in one_of_each()[:3]] == [False, True, True]


def test_every_event_type_is_unique() -> None:
    types = [e.type for e in one_of_each()]
    assert len(types) == len(set(types))


def test_usage_fields_mirror_usage() -> None:
    """I58: the event carries exactly the normalised Usage fields, so I51 semantics carry over."""
    usage_fields = set(Usage.model_fields)
    assert usage_fields <= set(LlmCallFinished.model_fields)


def test_events_reject_naive_time_and_bad_counts() -> None:
    with pytest.raises(ValidationError):
        StageStarted(at=T0.replace(tzinfo=None), stage="a")
    with pytest.raises(ValidationError):
        LlmRetryScheduled(at=T0, model=MODEL, transport_attempt=0, status=429, delay_s=1.0)
    with pytest.raises(ValidationError):
        StageFailed(at=T0, stage="a", error_code=" ")


def test_logging_sink_puts_fields_in_extra(caplog: pytest.LogCaptureFixture) -> None:
    event = StageFailed(at=T0, stage="ping", error_code="llm.transport")
    with caplog.at_level(logging.INFO, logger=LOGGER):
        LoggingEventSink().emit(event)
    (record,) = caplog.records
    assert record.getMessage() == "stage.failed"
    assert record.__dict__["pipeline_event"]["error_code"] == "llm.transport"


def test_every_event_declares_a_string_literal_type() -> None:
    for event in one_of_each():
        field = type(event).model_fields["type"]
        assert get_origin(field.annotation) is Literal
        assert get_args(field.annotation) == (field.default,) == (event.type,)
