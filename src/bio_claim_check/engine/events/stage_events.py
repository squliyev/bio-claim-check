"""[RING:engine/events] Stage boundaries: a named unit of work started, finished or failed.

Why: a run is a sequence of stages (an agent call today; retrieval, answer, verify from S10/S11), and a
reader of the event log needs to see where time went and where a run stopped.
`stage()` wraps a block: started, then finished, or failed with the `BccError`'s code. Any other
exception leaves the stage open, and the enclosing `run` stage records the run as internal or
cancelled. A trace-write failure is re-raised without another write, which would only hide it.
Must not: carry an error message (it may quote input): only the stable `BccError` code.

No LLM is involved in this module.
"""

import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Literal

from bio_claim_check.common.errors import BccError
from bio_claim_check.common.models import NonBlankStr
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.errors import EventWriteError
from bio_claim_check.engine.events.pipeline_event import PipelineEvent

logger = logging.getLogger(__name__)


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


@contextmanager
def stage(emitter: EventEmitter | None, name: str) -> Generator[None]:
    """Emit `name`'s start, then its finish, or its failure with the `BccError` code (re-raised)."""
    if emitter is None:
        yield
        return
    emitter.emit(lambda at: StageStarted(at=at, stage=name))
    try:
        yield
    except EventWriteError:
        raise  # the trace itself failed; writing to it again would only hide that
    except BccError as error:
        code = error.code
        try:
            emitter.emit(lambda at: StageFailed(at=at, stage=name, error_code=code))
        except EventWriteError as write_error:
            logger.error("could not record the failed stage %s: %s", name, type(write_error).__name__)
        raise
    emitter.emit(lambda at: StageFinished(at=at, stage=name))
