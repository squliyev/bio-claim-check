"""[RING:features/report] The one canonical serialisation of a report.

Why: a report must be byte-identical for identical inputs, so it can be diffed, hashed and cited. The
bytes are canonical (sorted keys, fixed indent, UTF-8, trailing newline; no timestamps or paths). Moved
here from infrastructure in S05b, so infrastructure only publishes bytes. Until S11 the run id was the
hash of these bytes; it is now the hash of the run manifest, which names this file's hash (ADR 0018).
Must not: write files, or add anything volatile (time, paths, durations) to the bytes.

No LLM is involved in this module.
"""

from typing import Final

from bio_claim_check.common.canonical_json import pretty_json_bytes
from bio_claim_check.features.report.models import Report

REPORT_FILE: Final = "report.json"


def canonical_bytes(report: Report) -> bytes:
    """The one serialisation used for both hashing and writing."""
    return pretty_json_bytes(report.model_dump(mode="json"))
