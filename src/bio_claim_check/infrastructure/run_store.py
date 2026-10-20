"""[RING:infrastructure] Write a report to disk as canonical, content-addressed JSON.

Why: a report must be byte-identical for identical inputs, so it can be diffed, hashed and cited. The
bytes are canonical (sorted keys, fixed indent, UTF-8, trailing newline; no timestamps or paths), and
the run id is the first 16 hex characters of their sha256. The id names the folder and is not stored
in the report, which would make it circular.
Must not: overwrite a different report. An existing `report.json` with other bytes under the same id
raises (a hash collision must be loud); identical bytes are a no-op. Publishing is no-clobber (a hard
link from a uniquely named, fsynced temp file), so two concurrent writers cannot replace each other.
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Final

from bio_claim_check.features.report.models import Report

REPORT_FILE: Final = "report.json"
RUN_ID_HEX: Final = 16


class RunStoreError(Exception):
    """A run could not be written without losing or corrupting data."""


def canonical_bytes(report: Report) -> bytes:
    """The one serialisation used for both hashing and writing."""
    text = json.dumps(report.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, indent=2)
    return (text + "\n").encode("utf-8")


def run_id(report: Report) -> str:
    return hashlib.sha256(canonical_bytes(report)).hexdigest()[:RUN_ID_HEX]


def write_report(out: Path, report: Report) -> Path:
    """Atomically write `<out>/<run_id>/report.json` and return its path."""
    data = canonical_bytes(report)
    folder = out / hashlib.sha256(data).hexdigest()[:RUN_ID_HEX]
    target = folder / REPORT_FILE
    folder.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return _same_or_refuse(target, data)
    fd, name = tempfile.mkstemp(prefix=f".{REPORT_FILE}.", suffix=".tmp", dir=folder)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, target)
        except FileExistsError:
            return _same_or_refuse(target, data)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def _same_or_refuse(target: Path, data: bytes) -> Path:
    if target.read_bytes() == data:
        return target
    raise RunStoreError(f"{target} exists with different content; refusing to overwrite")
