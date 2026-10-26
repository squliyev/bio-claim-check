"""[RING:app/usecases] Load one published run, after its whole hash chain is checked.

Why: a reader trusts a run's id, so everything shown under that id must hash to it. The manifest must
hash to the run id, the artifact to the manifest's record of it, and the artifact must parse as the
kind the command produces: a `Report` (`run`), a `DevRunRecord` (`run --dev`) or a `ClaimCheck`
(`check`), with the provenance its manifest names. Extracted in S17a from the retraction re-check, so
the UI and retractions share one loader (review R5).
Must not: read files or the clock (the caller passes bytes), repair or re-derive anything, or call an LLM.

No LLM is involved in this module.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final

from pydantic import ValidationError

from bio_claim_check.app.run_record import CheckInputs, RunManifest, run_id_of
from bio_claim_check.app.usecases.run_dev import DevRunRecord
from bio_claim_check.common.errors import BccError
from bio_claim_check.features.report.canonical import CHECK_FILE, REPORT_FILE
from bio_claim_check.features.report.models import ClaimCheck, Report

VIEWABLE_FILES: Final = (REPORT_FILE, CHECK_FILE)
"""The artifact names of the commands whose runs can be loaded; a run folder holds at most one."""
_RUN_ID: Final = re.compile(r"[0-9a-f]{16}")


class PublishedRunError(BccError):
    """The run id is malformed, or the run is missing, altered, or not a kind this loader knows."""

    code = "runs.published"


@dataclass(frozen=True, slots=True)
class PublishedRun:
    run_id: str
    manifest: RunManifest
    artifact: Report | DevRunRecord | ClaimCheck

    @property
    def report(self) -> Report | None:
        """The report of a `run` or `run --dev`; None for a check."""
        if isinstance(self.artifact, DevRunRecord):
            return self.artifact.report
        return self.artifact if isinstance(self.artifact, Report) else None


def validate_run_id(run_id: str) -> str:
    """`run_id` if it is 16 lowercase hex characters (it becomes a path), else `PublishedRunError`."""
    if not _RUN_ID.fullmatch(run_id):
        raise PublishedRunError(f"a run id is 16 lowercase hex characters, got {run_id!r}")
    return run_id


def parse_manifest(manifest: bytes, run_id: str) -> RunManifest:
    """The manifest, if it parses and hashes to `run_id`."""
    try:
        parsed = RunManifest.model_validate(json.loads(manifest))
    except (ValueError, ValidationError) as err:
        raise PublishedRunError(f"run {run_id}: the manifest does not parse") from err
    if run_id_of(manifest) != validate_run_id(run_id):
        raise PublishedRunError(f"run {run_id}: the manifest does not hash to the run id")
    return parsed


def load_published(run_id: str, manifest: bytes, artifact: bytes) -> PublishedRun:
    """The run, with its artifact parsed as the kind its manifest names."""
    parsed = parse_manifest(manifest, run_id)
    name = parsed.artifact.name
    expected = CHECK_FILE if parsed.command == "check" else REPORT_FILE if parsed.command == "run" else None
    if name != expected:
        raise PublishedRunError(f"run {run_id}: `{parsed.command}` runs with {name} cannot be shown")
    if hashlib.sha256(artifact).hexdigest() != parsed.artifact.sha256:
        raise PublishedRunError(f"run {run_id}: {name} does not match its manifest")
    inputs = parsed.inputs
    if isinstance(inputs, CheckInputs) != (parsed.command == "check"):
        raise PublishedRunError(f"run {run_id}: the manifest's inputs do not match its command")
    kind: type[Report | DevRunRecord | ClaimCheck] = Report
    if isinstance(inputs, CheckInputs):
        kind = ClaimCheck
    elif inputs.question_id is not None:
        kind = DevRunRecord
    try:
        loaded = kind.model_validate(json.loads(artifact))
    except (ValueError, ValidationError) as err:
        label = {Report: "report", DevRunRecord: "dev run record", ClaimCheck: "claim check"}[kind]
        raise PublishedRunError(f"run {run_id}: {name} is not a {label}") from err
    provenance = loaded.report.provenance if isinstance(loaded, DevRunRecord) else loaded.provenance
    if provenance != parsed.provenance:
        raise PublishedRunError(f"run {run_id}: {name} says {provenance}, its manifest {parsed.provenance}")
    if isinstance(loaded, ClaimCheck) and isinstance(inputs, CheckInputs):
        claim = loaded.claim.claim
        claim_sha256 = hashlib.sha256(claim.text.encode("utf-8")).hexdigest()
        if claim_sha256 != inputs.claim_sha256 or claim.cites != (inputs.source_id,):
            raise PublishedRunError(f"run {run_id}: {name} does not check what its manifest names")
    return PublishedRun(run_id=run_id, manifest=parsed, artifact=loaded)
