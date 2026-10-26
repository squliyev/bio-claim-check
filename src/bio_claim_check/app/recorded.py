"""[RING:app] The recorded commands that both driving adapters call: ask a question, check one claim.

Why: the CLI and the UI must record a run the same way (one manifest, one artifact, one ledger row), or
the trust report a reader opens in the UI could differ from the one the CLI wrote. Before S17a the CLI
wired `run` itself; this module is that wiring, moved so the UI cannot drift from it (ADR 0025).
`settings=None` means fictional: scripted papers and verdicts, no network, no `.env`.

`_RECORD_LOCK` serialises recorded commands inside one process, because Streamlit sessions share one
process and the ledger has one writer (review R4). Two processes at once (CLI and UI together) stay
unsupported, as `infrastructure.line_files` documents.
Must not: print, choose exit codes or user copy (the adapters do), or run `--dev` (a tuning record the
CLI keeps for itself).
"""

import hashlib
import threading
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from bio_claim_check.app.container import (
    RECORD_OUTPUT_ERRORS,
    DatasetReadError,
    MissingProviderError,
    UnsupportedProviderError,
    build_fake_check_ports,
    build_fake_run_ports,
    build_live_check_ports,
    build_live_run_ports,
    record_run,
    run_path,
)
from bio_claim_check.app.run_record import CheckInputs, RunDetails, RunInputs, RunRecorder
from bio_claim_check.app.settings import Settings
from bio_claim_check.app.usecases.check_claim import CheckInputError, HeldOutSourceError, check_claim
from bio_claim_check.app.usecases.run import RunInputError, run_question
from bio_claim_check.common.errors import BccError
from bio_claim_check.common.negation import NEGATION_RULES
from bio_claim_check.engine.cache.policy import CacheError, CacheMissError
from bio_claim_check.engine.events.pipeline_event import PipelineEvent
from bio_claim_check.engine.llm.errors import (
    LlmBudgetExceededError,
    LlmCallError,
    LlmPromptFilteredError,
    LlmProviderError,
    LlmRequestError,
    LlmTransportError,
    LlmUnexpectedResponseError,
)
from bio_claim_check.engine.llm.model_spec import UnknownDeploymentError
from bio_claim_check.features.answer.answer_models import AnswerClaimsError
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.contracts.rulepack import RulePackError
from bio_claim_check.features.contracts.verdict import Claim
from bio_claim_check.features.report.canonical import CHECK_FILE, REPORT_FILE, canonical_bytes
from bio_claim_check.features.report.models import ClaimCheck, Report
from bio_claim_check.features.retrieval.errors import NotCitableError, PaperNotFoundError, RetrievalError

_RECORD_LOCK: Final = threading.Lock()


class RecordBusyError(BccError):
    """Another recorded command is running in this process; the caller may retry when it ends."""

    code = "runs.busy"


UI_ERRORS: Final[tuple[type[BccError], ...]] = (
    RecordBusyError,
    RunInputError,
    CheckInputError,
    HeldOutSourceError,
    DatasetReadError,
    PaperNotFoundError,
    NotCitableError,
    CacheMissError,
    RetrievalError,
    CacheError,
    UnknownDeploymentError,
    MissingProviderError,
    UnsupportedProviderError,
    LlmCallError,
    LlmTransportError,
    LlmProviderError,
    LlmPromptFilteredError,
    LlmRequestError,
    LlmUnexpectedResponseError,
    LlmBudgetExceededError,
    AnswerClaimsError,
    RulePackError,
    *RECORD_OUTPUT_ERRORS,
)
"""Every error a recorded question or check raises on purpose; each has curated UI copy (I83)."""

EventsSeen = Callable[[Sequence[PipelineEvent]], None]


@dataclass(frozen=True, slots=True)
class Recorded[T]:
    """A published run: its id, the file it wrote, and the artifact."""

    run_id: str
    path: Path
    artifact: T


@contextmanager
def _recording(
    command: str, var_dir: Path, settings: Settings | None, on_events: EventsSeen | None
) -> Generator[RunRecorder]:
    if not _RECORD_LOCK.acquire(blocking=False):
        raise RecordBusyError("another run is in progress; try again when it ends")
    recorder: RunRecorder | None = None
    try:
        with record_run(var_dir, command, None if settings is None else settings.cache_mode) as recorder:
            yield recorder
    finally:
        _RECORD_LOCK.release()
        if recorder is not None and on_events is not None:
            on_events(recorder.events)


def _published[T](var_dir: Path, recorder: RunRecorder, name: str, artifact: T) -> Recorded[T]:
    if recorder.run_id is None:  # pragma: no cover - a recording that exited normally is published
        raise AssertionError("a run that returned normally is published")
    return Recorded(recorder.run_id, run_path(var_dir, recorder.run_id) / name, artifact)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_question(
    question: str,
    mode: AnswerMode,
    k: int,
    *,
    settings: Settings | None,
    var_dir: Path,
    on_events: EventsSeen | None = None,
) -> Recorded[Report]:
    """Answer `question`, check every claim, and publish `report.json` under `var_dir` (command `run`).

    `on_events` sees the run's events when the recording ends, published or not (the CLI prints usage).
    """
    with _recording("run", var_dir, settings, on_events) as recorder:
        if settings is None:
            ports = build_fake_run_ports(recorder.emitter)
            report = run_question(ports, question, mode, k=k)
            declared = ()
        else:
            with build_live_run_ports(settings, mode, recorder.emitter) as live:
                ports = live.ports
                report = run_question(ports, question, mode, k=k)
                declared = live.declared_llm
        details = RunDetails(
            provenance=ports.provenance,
            inputs=RunInputs(question_sha256=_sha256(question), mode=mode, k=k),
            negation_rules=NEGATION_RULES,
            rulepack_sha256=ports.rules_sha256,
            declared_llm=declared,
        )
        recorder.prepare(REPORT_FILE, canonical_bytes(report), details)
    return _published(var_dir, recorder, REPORT_FILE, report)


def record_check(
    claim: Claim,
    *,
    settings: Settings | None,
    var_dir: Path,
    on_events: EventsSeen | None = None,
) -> Recorded[ClaimCheck]:
    """Check one claim against the one paper it cites and publish `check.json` (command `check`, ADR 0025).

    Fictional (`settings=None`) takes a scripted claim on a `FAKE:` paper (`fake_check_claims`); live
    takes a user claim on a `MED:` id from `parse_pmid`.
    """
    with _recording("check", var_dir, settings, on_events) as recorder:
        if settings is None:
            ports = build_fake_check_ports(recorder.emitter)
            check = check_claim(ports, claim)
            declared = ()
        else:
            with build_live_check_ports(settings, recorder.emitter) as live:
                ports = live.ports
                check = check_claim(ports, claim)
                declared = live.declared_llm
        details = RunDetails(
            provenance=ports.provenance,
            inputs=CheckInputs(claim_sha256=_sha256(claim.text), source_id=claim.cites[0]),
            negation_rules=NEGATION_RULES,
            rulepack_sha256=ports.rules_sha256,
            declared_llm=declared,
        )
        recorder.prepare(CHECK_FILE, canonical_bytes(check), details)
    return _published(var_dir, recorder, CHECK_FILE, check)
