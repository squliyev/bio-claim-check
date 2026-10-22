"""[RING:engine/events] Stage boundaries: a named unit of work started, finished or failed.

Why: a run is a sequence of stages (an agent call today; retrieval, answer, verify from S10/S11), and a
reader of the event log needs to see where time went and where a run stopped.
Must not: carry an error message (it may quote input): only the stable `BccError` code.

No LLM is involved in this module.
"""

from typing import Literal

from bio_claim_check.common.models import NonBlankStr
from bio_claim_check.engine.events.pipeline_event import PipelineEvent


class StageStarted(PipelineEvent):
    type: Literal["stage.started"] = "stage.started"
    stage: NonBlankStr


class StageFinished(PipelineEvent):
    type: Literal["stage.finished"] = "stage.finished"
    stage: NonBlankStr


class StageFailed(PipelineEvent):
    type: Literal["stage.failed"] = "stage.failed"
    stage: NonBlankStr
    error_code: NonBlankStr


def is_terminal(event: PipelineEvent) -> bool:
    """Whether `event` closes its stage."""
    return isinstance(event, StageFinished | StageFailed)
