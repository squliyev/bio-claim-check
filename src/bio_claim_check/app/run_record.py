"""[RING:app] The run record: the canonical manifest, the ledger row, and the recorder that writes them.

Why: every command attempt must leave an honest record (ADR 0018): a successful run publishes its
artifact and then `manifest.json` (the commit marker; a run folder without it is incomplete) under
`runs/<run_id>/`, where the run id is the hash of the manifest, which names the artifact's hash. Every
attempt streams its events to `events/<UTC start>-<n>.jsonl` and appends exactly one row to `ledger.jsonl`
with its status, code and usage per model. Events go to memory first and then to the trace file, and the
manifest and ledger fold the memory copy, so a failed trace write cannot lose usage (I66, I67).
The recorder decides status as follows: it starts as failed with `run.internal`; a `BccError` sets its
code, `KeyboardInterrupt` sets cancelled with `run.cancelled`; success is set only after the body
returned, the `run` stage finished, the trace closed and both files were published. On any other path
the manifest is not published (the artifact may be, if the manifest itself then fails: that folder is
incomplete). The original exception always propagates: a write failure while another error is in
flight is logged by type, never raised over it.
It replaced the S05 run id (the hash of `report.json`) and `publish_report`.
Must not: import infrastructure (the container injects the file operations in `RecordIo`), read the wall
clock (it is injected), or put time, paths, cache mode or host in the manifest.

No LLM is involved in this module.
"""

import hashlib
import logging
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, fields
from datetime import UTC
from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from bio_claim_check.common.base_clock import BaseClock
from bio_claim_check.common.canonical_json import compact_json, pretty_json_bytes
from bio_claim_check.common.errors import BccError
from bio_claim_check.common.models import NonBlankStr, Sha256Hex, ValidatedModel
from bio_claim_check.engine.cache.policy import CacheMode
from bio_claim_check.engine.events.call_tally import paired_attempts, tally_calls
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.errors import EventWriteError
from bio_claim_check.engine.events.in_memory_event_sink import InMemoryEventSink
from bio_claim_check.engine.events.jsonl_event_sink import JsonlEventSink
from bio_claim_check.engine.events.llm_events import LlmCallFinished
from bio_claim_check.engine.events.pipeline_event import ModelRef, PipelineEvent
from bio_claim_check.engine.events.stage_events import StageFailed, StageFinished, StageStarted
from bio_claim_check.engine.events.tee_event_sink import TeeEventSink
from bio_claim_check.features.contracts.labels import AnswerMode

RUNS_DIR: Final = "runs"
EVENTS_DIR: Final = "events"
LEDGER_FILE: Final = "ledger.jsonl"
MANIFEST_FILE: Final = "manifest.json"
TRACE_SUFFIX: Final = ".jsonl"
RUN_ID_HEX: Final = 16
RUN_STAGE: Final = "run"
INTERNAL_CODE: Final = "run.internal"
CANCELLED_CODE: Final = "run.cancelled"

logger = logging.getLogger(__name__)
Count = Annotated[int, Field(strict=True, ge=0)]


class RunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LlmUse(ValidatedModel):
    """One distinct (agent, model, prompt, served model) that produced a response used by the run."""

    agent: NonBlankStr | None
    provider: NonBlankStr
    deployment: NonBlankStr
    model_version: NonBlankStr
    prompt_sha256: Sha256Hex | None
    served_model: NonBlankStr | None


class ArtifactRef(ValidatedModel):
    name: NonBlankStr
    sha256: Sha256Hex


class RunInputs(ValidatedModel):
    """`question_sha256` is the sha256 of the question's UTF-8 bytes as given (run); dev names its id."""

    question_sha256: Sha256Hex | None = None
    question_id: NonBlankStr | None = None
    mode: AnswerMode
    k: Annotated[int, Field(strict=True, ge=1)]


class DeclaredLlm(ValidatedModel):
    """One wired LLM role (agent) of a live run, named whether or not any of its calls finished, so a run
    whose verifier calls all failed, or that made none, still names the verifier's prompt (I71)."""

    agent: NonBlankStr
    provider: NonBlankStr
    deployment: NonBlankStr
    model_version: NonBlankStr
    prompt_sha256: Sha256Hex


class RunDetails(ValidatedModel):
    """What the command knows about its run; the recorder adds the artifact, LLM uses and version.
    `declared_llm` is the wired roles, sorted by agent (at least one for a live run, none for a fake one);
    `llm` (on the manifest) is what was observed."""

    provenance: Literal["fake", "live"]
    inputs: RunInputs
    negation_rules: Annotated[int, Field(strict=True, ge=1)]
    rulepack_sha256: Sha256Hex | None = None
    dataset_manifest_sha256: Sha256Hex | None = None
    declared_llm: tuple[DeclaredLlm, ...] = ()

    @model_validator(mode="after")
    def _declared_sorted(self) -> Self:
        agents = [d.agent for d in self.declared_llm]
        if agents != sorted(set(agents)):
            raise ValueError("declared_llm: one entry per agent, sorted by agent")
        if (self.provenance == "live") != bool(agents):
            raise ValueError("declared_llm: required for a live run, empty for a fake one")
        return self


class RunManifest(RunDetails):
    """Canonical: the same inputs, code version and cached responses give the same bytes (I65)."""

    manifest_version: Literal[1] = 1
    command: NonBlankStr
    package_version: NonBlankStr
    artifact: ArtifactRef
    llm: tuple[LlmUse, ...]


class ModelUsage(ValidatedModel):
    """`engine.events.call_tally.CallTally` for one model, as stored in the ledger."""

    model: ModelRef
    finished_attempts: Count
    cache_hits: Count
    failed_calls: Count
    unmeasured_attempts: Count
    transport_retries: Count
    measured_input_tokens: Count
    measured_output_tokens: Count
    measured_reasoning_tokens: Count
    reasoning_unreported: Count


class LedgerRow(ValidatedModel):
    """One command attempt. No question text, no paths, no cost (no deployment is priced yet, A13)."""

    ledger_version: Literal[1] = 1
    started_at: AwareDatetime
    finished_at: AwareDatetime
    command: NonBlankStr
    status: RunStatus
    code: NonBlankStr | None
    run_id: NonBlankStr | None
    events: NonBlankStr | None
    cache_mode: CacheMode | None
    usage: tuple[ModelUsage, ...]


def _none_last(value: str | None) -> str:
    return "" if value is None else value


def llm_uses(events: Sequence[PipelineEvent]) -> tuple[LlmUse, ...]:
    """The distinct LLM uses that returned a response, sorted (None sorts as "")."""
    uses: dict[tuple[str, ...], LlmUse] = {}
    for start, end in paired_attempts(events):
        if isinstance(end, LlmCallFinished):
            use = LlmUse(
                agent=start.agent,
                provider=start.model.provider,
                deployment=start.model.deployment,
                model_version=start.model.model_version,
                prompt_sha256=start.prompt_sha256,
                served_model=end.served_model,
            )
            key = (
                _none_last(use.agent),
                use.provider,
                use.deployment,
                use.model_version,
                _none_last(use.prompt_sha256),
                _none_last(use.served_model),
            )
            uses[key] = use
    return tuple(uses[key] for key in sorted(uses))


def usage_rows(events: Sequence[PipelineEvent]) -> tuple[ModelUsage, ...]:
    tallies = tally_calls(events)
    rows = (
        ModelUsage(model=model, **{f.name: getattr(t, f.name) for f in fields(t)})
        for model, t in tallies.items()
    )
    return tuple(sorted(rows, key=lambda r: (r.model.provider, r.model.deployment, r.model.model_version)))


def run_manifest_json_schema() -> dict[str, JsonValue]:
    return RunManifest.model_json_schema(mode="serialization")


def ledger_row_json_schema() -> dict[str, JsonValue]:
    return LedgerRow.model_json_schema(mode="serialization")


def manifest_bytes(manifest: RunManifest) -> bytes:
    return pretty_json_bytes(manifest.model_dump(mode="json"))


def run_id_of(manifest: bytes) -> str:
    """The first 16 hex characters of the manifest bytes' sha256."""
    return hashlib.sha256(manifest).hexdigest()[:RUN_ID_HEX]


def ledger_line(row: LedgerRow) -> bytes:
    """One canonical compact JSON line, without its newline."""
    return compact_json(row.model_dump(mode="json")).encode("utf-8")


def trace_stem(started: AwareDatetime) -> str:
    return started.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


@dataclass(frozen=True, slots=True)
class TraceHandle:
    """An opened trace file: its file name, a line writer and a closer (both raise `EventWriteError`)."""

    name: str
    write_line: Callable[[bytes], None]
    close: Callable[[], None]


@dataclass(frozen=True, slots=True)
class RecordIo:
    """The file operations, injected by the container. Each raises only a `BccError`.

    - `open_trace(stem)` creates a new trace file (`EventWriteError` if it cannot);
    - `publish(run_id, name, data)` publishes once under `runs/<run_id>/`;
    - `append_ledger(line)` appends one line to the ledger.
    """

    open_trace: Callable[[str], TraceHandle]
    publish: Callable[[str, str, bytes], None]
    append_ledger: Callable[[bytes], None]


@dataclass(frozen=True, slots=True)
class _Prepared:
    name: str
    data: bytes
    details: RunDetails


class RunRecorder:
    """Handed to the command: emit through `emitter`, then `prepare` the artifact. Publishing happens on
    a clean exit only; `run_id` is set after it."""

    def __init__(self, emitter: EventEmitter, memory: InMemoryEventSink) -> None:
        self.emitter = emitter
        self._memory = memory
        self._prepared: _Prepared | None = None
        self.run_id: str | None = None

    @property
    def events(self) -> tuple[PipelineEvent, ...]:
        return self._memory.events

    def prepare(self, name: str, data: bytes, details: RunDetails) -> None:
        if self._prepared is not None:
            raise RuntimeError("a run prepares one artifact")
        if name == MANIFEST_FILE:
            raise RuntimeError(f"an artifact may not be named {MANIFEST_FILE}, the commit marker")
        self._prepared = _Prepared(name, data, details)

    def take_prepared(self) -> _Prepared:
        if self._prepared is None:
            raise RuntimeError("the run ended without preparing its artifact")
        return self._prepared


def build_manifest(
    prepared: _Prepared, events: Sequence[PipelineEvent], command: str, package_version: str
) -> RunManifest:
    return RunManifest(
        **prepared.details.model_dump(),
        command=command,
        package_version=package_version,
        artifact=ArtifactRef(name=prepared.name, sha256=hashlib.sha256(prepared.data).hexdigest()),
        llm=llm_uses(events),
    )


def _quietly(what: str, action: Callable[[], object]) -> None:
    """Run `action` while another exception is propagating: a typed failure is logged, never raised."""
    try:
        action()
    except BccError as error:
        logger.error("could not %s: %s", what, type(error).__name__)


@dataclass(slots=True)
class _Attempt:
    status: RunStatus = RunStatus.FAILED
    code: str | None = INTERNAL_CODE
    events: str | None = None
    run_id: str | None = None


@contextmanager
def recording(
    io: RecordIo,
    clock: BaseClock,
    command: str,
    cache_mode: CacheMode | None,
    package_version: str,
) -> Generator[RunRecorder]:
    """Record one command attempt; see the module docstring for the status rules."""
    started = clock.now()
    memory = InMemoryEventSink()
    attempt = _Attempt()
    trace: TraceHandle | None = None
    recorder: RunRecorder | None = None
    clean = False
    try:
        trace = io.open_trace(trace_stem(started))
        attempt.events = trace.name
        recorder = RunRecorder(
            EventEmitter(TeeEventSink(memory, JsonlEventSink(trace.write_line)), clock), memory
        )
        recorder.emitter.emit(lambda at: StageStarted(at=at, stage=RUN_STAGE))
        yield recorder
        prepared = recorder.take_prepared()
        recorder.emitter.emit(lambda at: StageFinished(at=at, stage=RUN_STAGE))
        closing, trace = trace, None
        closing.close()
        manifest = manifest_bytes(build_manifest(prepared, memory.events, command, package_version))
        run_id = run_id_of(manifest)
        io.publish(run_id, prepared.name, prepared.data)
        io.publish(run_id, MANIFEST_FILE, manifest)
        recorder.run_id = attempt.run_id = run_id
        attempt.status, attempt.code = RunStatus.SUCCEEDED, None
        clean = True
    except KeyboardInterrupt:
        attempt.status, attempt.code = RunStatus.CANCELLED, CANCELLED_CODE
        raise
    except BccError as error:
        attempt.code = error.code
        raise
    finally:
        if not clean:
            _close_failed(recorder, trace, attempt.code or INTERNAL_CODE)
        row = LedgerRow(
            started_at=started,
            finished_at=clock.now(),
            command=command,
            status=attempt.status,
            code=attempt.code,
            run_id=attempt.run_id,
            events=attempt.events,
            cache_mode=cache_mode,
            usage=usage_rows(memory.events),
        )
        if clean:
            io.append_ledger(ledger_line(row))
        else:
            _quietly("append the ledger row", lambda: io.append_ledger(ledger_line(row)))


def _close_failed(recorder: RunRecorder | None, trace: TraceHandle | None, code: str) -> None:
    """Close the `run` stage as failed and the trace, while the original exception propagates."""
    if trace is None:
        return
    if recorder is not None and code != EventWriteError.code:
        emitter = recorder.emitter
        _quietly(
            "record the failed run",
            lambda: emitter.emit(lambda at: StageFailed(at=at, stage=RUN_STAGE, error_code=code)),
        )
    _quietly("close the trace", trace.close)
