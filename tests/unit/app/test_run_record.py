"""The run record (ADR 0018): canonical manifest and run id (I65), one honest ledger row per attempt (I66)."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest
from tests.support.events import HASH, MODEL, T0, stepping_clock

from bio_claim_check.app.run_record import (
    LlmUse,
    RecordIo,
    RunDetails,
    RunInputs,
    RunRecorder,
    TraceHandle,
    llm_uses,
    recording,
    run_id_of,
)
from bio_claim_check.engine.cache.policy import CacheMode
from bio_claim_check.engine.events.errors import EventWriteError
from bio_claim_check.engine.events.llm_events import LlmCallFinished, LlmCallStarted
from bio_claim_check.engine.events.pipeline_event import PipelineEvent
from bio_claim_check.engine.llm.errors import LlmTransportError
from bio_claim_check.features.contracts.labels import AnswerMode

pytestmark = pytest.mark.unit

DETAILS = RunDetails(
    provenance="live", inputs=RunInputs(question_id="q1", mode=AnswerMode.STRICT, k=3), negation_rules=1
)
BOOM = LlmTransportError(deployment="d", status=503, attempts=3, reason="unavailable")


class FakeIo:
    """Records every file operation; any of them can be made to fail."""

    def __init__(self) -> None:
        self.trace: list[bytes] = []
        self.published: list[tuple[str, str, bytes]] = []
        self.ledger: list[bytes] = []
        self.closed = 0
        self.fail: dict[str, BaseException] = {}
        self.fail_line_after: int | None = None

    def _maybe(self, what: str) -> None:
        if what in self.fail:
            raise self.fail[what]

    def open_trace(self, stem: str) -> TraceHandle:
        self._maybe("open")
        return TraceHandle(name=f"{stem}-0.jsonl", write_line=self._write, close=self._close)

    def _write(self, line: bytes) -> None:
        if self.fail_line_after is not None and len(self.trace) >= self.fail_line_after:
            raise OSError(28, "No space left on device")
        self.trace.append(line)

    def _close(self) -> None:
        self.closed += 1
        self._maybe("close")

    def publish(self, run_id: str, name: str, data: bytes) -> None:
        self._maybe(f"publish:{name}")
        self.published.append((run_id, name, data))

    def append(self, line: bytes) -> None:
        self._maybe("append")
        self.ledger.append(line)

    def io(self) -> RecordIo:
        return RecordIo(open_trace=self.open_trace, publish=self.publish, append_ledger=self.append)

    def row(self) -> dict[str, Any]:
        (line,) = self.ledger
        return json.loads(line)

    def trace_types(self) -> list[tuple[str, str | None]]:
        return [(e["type"], e.get("stage")) for e in map(json.loads, self.trace)]


def started(at: datetime = T0) -> LlmCallStarted:
    return LlmCallStarted(
        at=at, agent="a", model=MODEL, attempt=1, repeat_idx=0, request_hash=HASH, prompt_sha256=HASH
    )


def finished(served: str | None = "m-1", *, cache_hit: bool = False, at: datetime = T0) -> LlmCallFinished:
    return LlmCallFinished(
        at=at,
        agent="a",
        model=MODEL,
        attempt=1,
        finish_reason="stop",
        cache_hit=cache_hit,
        served_model=served,
        input_tokens=3,
        output_tokens=2,
        reasoning_tokens=None,
        cached_input_tokens=0,
    )


def record(
    io: FakeIo, body: Callable[[RunRecorder], None], *, cache_mode: CacheMode | None = CacheMode.READ_WRITE
) -> None:
    with recording(io.io(), stepping_clock(), "answer dev", cache_mode, "1.2.3") as recorder:
        body(recorder)


def _succeeds(recorder: RunRecorder) -> None:
    recorder.emitter.emit(started)
    recorder.emitter.emit(lambda at: finished(at=at))
    recorder.prepare("answer.json", b"{}\n", DETAILS)


def test_success_publishes_the_artifact_then_the_manifest_named_by_its_hash() -> None:
    io = FakeIo()
    record(io, _succeeds)
    (run_a, artifact, data), (run_m, manifest_name, manifest) = io.published
    assert (artifact, data, manifest_name) == ("answer.json", b"{}\n", "manifest.json")
    assert run_a == run_m == run_id_of(manifest) == hashlib.sha256(manifest).hexdigest()[:16]
    m = json.loads(manifest)
    assert m["artifact"] == {"name": "answer.json", "sha256": hashlib.sha256(b"{}\n").hexdigest()}
    assert (m["command"], m["package_version"], m["provenance"]) == ("answer dev", "1.2.3", "live")
    assert [u["served_model"] for u in m["llm"]] == ["m-1"]
    for volatile in ("2026", "read-write", "cache", "events", "at"):
        assert volatile not in m, volatile
    assert "2026" not in manifest.decode()
    row = io.row()
    assert (row["status"], row["code"], row["run_id"], row["cache_mode"]) == (
        "succeeded",
        None,
        run_a,
        "read-write",
    )
    assert row["events"] == "20260101T000000Z-0.jsonl"
    assert io.trace_types()[0] == ("stage.started", "run")
    assert io.trace_types()[-1] == ("stage.finished", "run")
    assert io.closed == 1


def test_the_same_run_gives_the_same_manifest_and_run_id() -> None:
    first, second = FakeIo(), FakeIo()
    record(first, _succeeds)
    record(second, _succeeds, cache_mode=CacheMode.READ_ONLY)
    assert first.published == second.published


@pytest.mark.parametrize(
    ("raised", "status", "code"),
    [
        (BOOM, "failed", "llm.transport"),
        (KeyboardInterrupt(), "cancelled", "run.cancelled"),
        (RuntimeError("bug"), "failed", "run.internal"),
    ],
    ids=["typed", "cancelled", "internal"],
)
def test_a_body_failure_is_re_raised_publishes_nothing_and_leaves_one_row(
    raised: BaseException, status: str, code: str
) -> None:
    io = FakeIo()

    def body(recorder: RunRecorder) -> None:
        _succeeds(recorder)
        raise raised

    with pytest.raises(type(raised)) as caught:
        record(io, body)
    assert caught.value is raised
    assert io.published == []
    row = io.row()
    assert (row["status"], row["code"], row["run_id"]) == (status, code, None)
    assert row["usage"][0]["finished_attempts"] == 1
    last = json.loads(io.trace[-1])
    assert (last["type"], last["stage"], last["error_code"]) == ("stage.failed", "run", code)
    assert io.closed == 1


def test_a_body_that_does_not_prepare_is_an_internal_failure() -> None:
    io = FakeIo()
    with pytest.raises(RuntimeError, match="without preparing"):
        record(io, lambda _: None)
    assert (io.row()["status"], io.row()["code"]) == ("failed", "run.internal")
    assert io.published == []


def test_a_trace_that_cannot_be_opened_still_leaves_a_row_without_events() -> None:
    io = FakeIo()
    io.fail["open"] = EventWriteError("all names taken")
    with pytest.raises(EventWriteError):
        record(io, _succeeds)
    row = io.row()
    assert (row["status"], row["code"], row["events"]) == ("failed", "events.write", None)


def test_a_trace_write_failure_keeps_the_usage_in_the_row() -> None:
    io = FakeIo()
    io.fail_line_after = 2  # run started and the call started reach the file; the finish does not
    with pytest.raises(EventWriteError):
        record(io, _succeeds)
    row = io.row()
    assert (row["status"], row["code"]) == ("failed", "events.write")
    assert row["usage"][0]["finished_attempts"] == 1
    assert io.published == []


@pytest.mark.parametrize(
    ("failing", "left"),
    [("close", []), ("publish:answer.json", []), ("publish:manifest.json", ["answer.json"])],
)
def test_a_finalisation_failure_is_a_failed_row_and_the_manifest_is_not_published(
    failing: str, left: list[str]
) -> None:
    io = FakeIo()
    io.fail[failing] = EventWriteError("disk full")
    with pytest.raises(EventWriteError):
        record(io, _succeeds)
    assert (io.row()["status"], io.row()["run_id"]) == ("failed", None)
    assert [name for _, name, _ in io.published] == left  # without its manifest, a folder is incomplete
    assert io.closed == 1


def test_the_artifact_may_not_be_named_like_the_manifest() -> None:
    io = FakeIo()

    def body(recorder: RunRecorder) -> None:
        recorder.prepare("manifest.json", b"{}", DETAILS)

    with pytest.raises(RuntimeError, match="manifest"):
        record(io, body)
    assert io.published == []


def test_a_ledger_failure_on_success_raises_and_on_failure_the_original_error_wins() -> None:
    io = FakeIo()
    io.fail["append"] = EventWriteError("cannot append")
    with pytest.raises(EventWriteError, match="cannot append"):
        record(io, _succeeds)

    io = FakeIo()
    io.fail["append"] = EventWriteError("cannot append")

    def body(recorder: RunRecorder) -> None:
        del recorder
        raise BOOM

    with pytest.raises(LlmTransportError):
        record(io, body)


def test_llm_uses_are_distinct_sorted_with_none_first_and_count_only_responses() -> None:
    events: list[PipelineEvent] = [
        started(),
        finished("z"),
        started(),
        finished(None, cache_hit=True),
        started(),
        finished("z"),
        started(),  # never ended: not a use
    ]
    assert [u.served_model for u in llm_uses(events)] == [None, "z"]
    assert all(isinstance(u, LlmUse) for u in llm_uses(events))
