"""[RING:features/report] The one canonical serialisation of a report, and the run id derived from it.

Why: a report must be byte-identical for identical inputs, so it can be diffed, hashed and cited. The
bytes are canonical (sorted keys, fixed indent, UTF-8, trailing newline; no timestamps or paths), and
the run id is the first 16 hex characters of their sha256. The id names the run folder and is not
stored in the report, which would make it circular. Moved here from infrastructure in S05b, so
infrastructure only publishes bytes.
Must not: write files, or add anything volatile (time, paths, durations) to the bytes.

No LLM is involved in this module.
"""

import hashlib
import json
from typing import Final

from bio_claim_check.features.report.models import Report

REPORT_FILE: Final = "report.json"
RUN_ID_HEX: Final = 16


def canonical_bytes(report: Report) -> bytes:
    """The one serialisation used for both hashing and writing."""
    text = json.dumps(report.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, indent=2)
    return (text + "\n").encode("utf-8")


def run_id(data: bytes) -> str:
    """The run id of canonical report bytes."""
    return hashlib.sha256(data).hexdigest()[:RUN_ID_HEX]
