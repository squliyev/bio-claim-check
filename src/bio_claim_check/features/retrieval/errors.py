"""[RING:features/retrieval] The one error a literature source raises when the database fails.

Why: callers (the CLI, later the run use case) must tell "the database failed" apart from "bad input"
(`ValueError`) and "not in the replay cache" (`CacheMissError`) without importing a backend or httpx.
Must not: carry request headers or the contact email in its message.

No LLM is involved in this module.
"""

from bio_claim_check.common.errors import BccError


class RetrievalError(BccError):
    """The literature database could not be reached, refused the request or sent a malformed response."""

    code = "retrieval.failed"
