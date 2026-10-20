"""[RING:features/contracts] Identifier types for claims and cited sources.

Why: ids are join keys (claim to source, item to outcome). A pattern rejects blank or whitespace ids at
the edge, so a bad id fails on parse instead of silently creating a second, unjoinable row.
Must not: encode meaning (trap kind, parent item) in an id; the verifier sees ids, so they stay opaque.

No LLM is involved in this module.
"""

from typing import Annotated

from pydantic import StringConstraints

ClaimId = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9_-]{1,64}$")]
"""Opaque claim id, unique within one answer."""

SourceId = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Z]{2,10}:[A-Za-z0-9._-]{1,64}$")]
"""A cited source, namespaced by its database, e.g. ``MED:12345678`` or ``PMC:PMC1234567``."""
