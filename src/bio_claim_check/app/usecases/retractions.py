"""[RING:app/usecases] Re-check the retraction status of every paper a recorded live run cited.

Why: `Paper.retracted` is a snapshot from the run's fetch (ADR 0009), and a paper can be retracted later.
This re-asks the database about exactly the cited ids, uncached and without the citable filters, and
reports both values side by side (ADR 0019). The run is identified by its id and checked first: the
manifest must hash to the id, the artifact must hash to the manifest's record of it, and the run must be
a live `run` (a fake run cites fictional ids; a dev artifact is a tuning record). All of that is checked
before any request.
Must not: modify, re-publish or re-derive anything under the run's folder; read files or the clock (the
caller passes bytes and a time); call an LLM.

No LLM is involved in this module.
"""

import hashlib
import json
import re
from collections.abc import Sequence
from typing import Final

from pydantic import AwareDatetime, ValidationError

from bio_claim_check.app.run_record import RunManifest, run_id_of
from bio_claim_check.common.errors import BccError
from bio_claim_check.common.models import ValidatedModel
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.report.models import Report
from bio_claim_check.features.retrieval.models import RetractionStatus

REPORT_FILE: Final = "report.json"
RECHECKED_NAMESPACE: Final = "MED:"
_RUN_ID = re.compile(r"[0-9a-f]{16}")


class RetractionInputError(BccError):
    """The run id is malformed, or the run is missing, altered, not a live `run`, or not a report."""

    code = "retractions.input"


class RetractionRow(ValidatedModel):
    """`retracted_in_run` is None for a cited id the run never retrieved; `retracted_now` is None when the
    database no longer holds a record for it."""

    source_id: SourceId
    retracted_in_run: bool | None
    retracted_now: bool | None


class RetractionCheck(ValidatedModel):
    """One re-check of one run. Not canonical: `checked_at` and the database's answers change over time."""

    check_version: int = 1
    run_id: str
    checked_at: AwareDatetime
    papers: tuple[RetractionRow, ...]


def validate_run_id(run_id: str) -> str:
    """`run_id` if it is 16 lowercase hex characters (it becomes a path), else `RetractionInputError`."""
    if not _RUN_ID.fullmatch(run_id):
        raise RetractionInputError(f"a run id is 16 lowercase hex characters, got {run_id!r}")
    return run_id


def load_checked_run(manifest: bytes, artifact: bytes, run_id: str) -> Report:
    """The run's report, after the hash chain and the run kind are checked (before any request)."""
    try:
        parsed = RunManifest.model_validate(json.loads(manifest))
    except (ValueError, ValidationError) as err:
        raise RetractionInputError(f"run {run_id}: the manifest does not parse") from err
    if run_id_of(manifest) != run_id:
        raise RetractionInputError(f"run {run_id}: the manifest does not hash to the run id")
    if parsed.provenance != "live":
        raise RetractionInputError(f"run {run_id}: a {parsed.provenance} run cites no real papers")
    if parsed.command != "run" or parsed.artifact.name != REPORT_FILE:
        raise RetractionInputError(f"run {run_id}: not a recorded `run` report ({parsed.command})")
    if parsed.inputs.question_id is not None:
        raise RetractionInputError(f"run {run_id}: a --dev run is a tuning record, not a checked answer")
    if hashlib.sha256(artifact).hexdigest() != parsed.artifact.sha256:
        raise RetractionInputError(f"run {run_id}: {REPORT_FILE} does not match its manifest")
    try:
        report = Report.model_validate(json.loads(artifact))
    except (ValueError, ValidationError) as err:
        raise RetractionInputError(f"run {run_id}: {REPORT_FILE} is not a report") from err
    if report.provenance != parsed.provenance:
        raise RetractionInputError(f"run {run_id}: {REPORT_FILE} says {report.provenance}, its manifest live")
    return report


def cited_ids(report: Report) -> tuple[SourceId, ...]:
    """Every unique cited `MED:` id, retrieved or not, sorted."""
    return tuple(
        sorted({s for c in report.claims for s in c.claim.cites if s.startswith(RECHECKED_NAMESPACE)})
    )


def retraction_check(
    report: Report, statuses: Sequence[RetractionStatus], run_id: str, checked_at: AwareDatetime
) -> RetractionCheck:
    """Fold the run's snapshot and the current statuses into one row per cited id.

    Raises:
        ValueError: `statuses` is not exactly one status per cited id, in `cited_ids` order.
    """
    ids = cited_ids(report)
    if tuple(s.source_id for s in statuses) != ids:
        raise ValueError("statuses must answer every cited id, in order")
    in_run = {p.source_id: p.retracted for p in report.papers}
    return RetractionCheck(
        run_id=run_id,
        checked_at=checked_at,
        papers=tuple(
            RetractionRow(
                source_id=s.source_id, retracted_in_run=in_run.get(s.source_id), retracted_now=s.retracted
            )
            for s in statuses
        ),
    )
