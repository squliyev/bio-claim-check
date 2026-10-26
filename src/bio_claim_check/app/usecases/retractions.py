"""[RING:app/usecases] Re-check the retraction status of every paper a recorded live run cited.

Why: `Paper.retracted` is a snapshot from the run's fetch (ADR 0009), and a paper can be retracted later.
This re-asks the database about exactly the cited ids, uncached and without the citable filters, and
reports both values side by side (ADR 0019). The run is identified by its id and checked first: the
manifest must hash to the id, the artifact must hash to the manifest's record of it, and the run must be
a live `run` (a fake run cites fictional ids; a dev artifact is a tuning record). All of that is checked
before any request; the hash chain is `published_run.load_published`, shared with the UI (S17a).
Must not: modify, re-publish or re-derive anything under the run's folder; read files or the clock (the
caller passes bytes and a time); call an LLM.

No LLM is involved in this module.
"""

from collections.abc import Sequence
from typing import Final

from pydantic import AwareDatetime

from bio_claim_check.app.run_record import RunInputs
from bio_claim_check.app.usecases import published_run
from bio_claim_check.app.usecases.published_run import PublishedRunError, load_published, parse_manifest
from bio_claim_check.common.errors import BccError
from bio_claim_check.common.models import ValidatedModel
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.report.models import Report
from bio_claim_check.features.retrieval.models import RetractionStatus

REPORT_FILE: Final = "report.json"
RECHECKED_NAMESPACE: Final = "MED:"


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
    try:
        return published_run.validate_run_id(run_id)
    except PublishedRunError as err:
        raise RetractionInputError(str(err)) from None


def load_checked_run(manifest: bytes, artifact: bytes, run_id: str) -> Report:
    """The run's report, after the hash chain (`load_published`) and the run kind are checked."""
    try:
        parsed = parse_manifest(manifest, run_id)
    except PublishedRunError as err:
        raise RetractionInputError(str(err)) from None
    if parsed.provenance != "live":
        raise RetractionInputError(f"run {run_id}: a {parsed.provenance} run cites no real papers")
    if parsed.command != "run" or parsed.artifact.name != REPORT_FILE:
        raise RetractionInputError(f"run {run_id}: not a recorded `run` report ({parsed.command})")
    if isinstance(parsed.inputs, RunInputs) and parsed.inputs.question_id is not None:
        raise RetractionInputError(f"run {run_id}: a --dev run is a tuning record, not a checked answer")
    try:
        run = load_published(run_id, manifest, artifact)
    except PublishedRunError as err:
        raise RetractionInputError(str(err)) from None
    if not isinstance(run.artifact, Report):  # pragma: no cover - the kind checks above exclude it
        raise RetractionInputError(f"run {run_id}: not a report")
    return run.artifact


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
