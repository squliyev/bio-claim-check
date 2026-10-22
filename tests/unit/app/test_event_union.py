import pytest
from pydantic import ValidationError
from tests.support.events import one_of_each
from tests.support.guards import import_package

from bio_claim_check.app.events import AnyPipelineEvent, parse_event
from bio_claim_check.engine.events.pipeline_event import PipelineEvent

pytestmark = pytest.mark.unit


def _union_members() -> list[type]:
    union = AnyPipelineEvent.__value__.__origin__
    return list(union.__args__)


def _concrete_events() -> set[type]:
    modules = import_package("bio_claim_check")
    return {
        obj
        for module in modules.values()
        for obj in vars(module).values()
        if isinstance(obj, type)
        and issubclass(obj, PipelineEvent)
        and obj is not PipelineEvent
        and obj.__module__ == module.__name__
    }


def test_every_event_class_is_in_the_union_exactly_once() -> None:
    """I58: a new event that is not added to the union fails here."""
    members = _union_members()
    assert len(members) == len(set(members))
    assert set(members) == _concrete_events()


def test_fixture_covers_every_member() -> None:
    assert {type(e) for e in one_of_each()} == set(_union_members())


@pytest.mark.parametrize("event", one_of_each(), ids=lambda e: e.type)
def test_round_trip(event: PipelineEvent) -> None:
    assert parse_event(event.model_dump_json()) == event


def test_unknown_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_event(b'{"type": "llm.mystery", "at": "2026-01-01T00:00:00Z"}')
