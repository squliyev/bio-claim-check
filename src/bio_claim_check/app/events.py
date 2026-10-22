"""[RING:app] The closed union of every pipeline event, and the one way to parse an event back.

Why: events are defined where their vocabulary lives (generic ones in `engine.events`, domain ones in
`features.contracts` from S10), and only `app` may see both, so the closed discriminated union is
assembled here (ADR 0016). A test proves every `PipelineEvent` subclass appears exactly once (I58);
`make schemas` exports the union so the S11 writer and S17 UI validate against one schema.
Must not: define events, or accept an event type that is not in the union.

No LLM is involved in this module.
"""

from typing import Annotated, Final

from pydantic import Field, JsonValue, TypeAdapter

from bio_claim_check.engine.events.llm_events import (
    LlmCallFailed,
    LlmCallFinished,
    LlmCallStarted,
    LlmRepairRequested,
    LlmRetryScheduled,
)
from bio_claim_check.engine.events.pipeline_event import PipelineEvent
from bio_claim_check.engine.events.stage_events import StageFailed, StageFinished, StageStarted

type AnyPipelineEvent = Annotated[
    StageStarted
    | StageFinished
    | StageFailed
    | LlmCallStarted
    | LlmCallFinished
    | LlmRepairRequested
    | LlmCallFailed
    | LlmRetryScheduled,
    Field(discriminator="type"),
]

PIPELINE_EVENT: Final = TypeAdapter[AnyPipelineEvent](AnyPipelineEvent)


def parse_event(data: str | bytes) -> PipelineEvent:
    """One event from its JSON; an unknown `type` or a bad field raises `ValidationError`."""
    return PIPELINE_EVENT.validate_json(data)


def pipeline_event_json_schema() -> dict[str, JsonValue]:
    return PIPELINE_EVENT.json_schema(mode="validation")
