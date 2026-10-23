"""[RING:features/retrieval] What retrieval reports besides papers: a paper's current retraction status.

Why: the retraction re-check (ADR 0019) asks the database about exact ids, including cited ids that were
never retrieved, so its answer cannot be a `Paper` (an absent or no-longer-citable record has none).
Must not: carry anything but the id and the status.

No LLM is involved in this module.
"""

from typing import Annotated

from pydantic import Field

from bio_claim_check.common.models import ValidatedModel
from bio_claim_check.features.contracts.ids import SourceId


class RetractionStatus(ValidatedModel):
    """`retracted` is None when the database holds no record for the id (not found, or not its namespace)."""

    source_id: SourceId
    retracted: Annotated[bool, Field(strict=True)] | None
