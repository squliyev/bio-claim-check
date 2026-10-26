"""[RING:features/retrieval] The errors a literature source raises on purpose.

Why: callers (the CLI, later the run use case) must tell "the database failed" apart from "bad input"
(`ValueError`) and "not in the replay cache" (`CacheMissError`) without importing a backend or httpx.
`fetch` (S17a) adds two outcomes a caller must tell apart: the id is not in the database, or it is but
the record is not citable (no abstract, a letter, …).
Must not: carry request headers or the contact email in its message.

No LLM is involved in this module.
"""

from bio_claim_check.common.errors import BccError
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.retrieval.citable import RejectReason


class RetrievalError(BccError):
    """The literature database could not be reached, refused the request or sent a malformed response."""

    code = "retrieval.failed"


class PaperNotFoundError(BccError):
    """`fetch`: the database holds no record for the id."""

    code = "retrieval.not_found"

    def __init__(self, source_id: SourceId) -> None:
        super().__init__(f"{source_id}: no record in the literature database")
        self.source_id = source_id


class NotCitableError(BccError):
    """`fetch`: the record exists but is not a citable paper (ADR 0008), so no claim is checked against it."""

    code = "retrieval.not_citable"

    def __init__(self, source_id: SourceId, reason: RejectReason) -> None:
        super().__init__(f"{source_id}: not a citable paper ({reason.value})")
        self.source_id = source_id
        self.reason = reason
