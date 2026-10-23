"""[RING:features/retrieval] The port retrieval owns: where citable papers come from.

Why: the use case depends on this base, never on a backend. Implementations subclass it and sit beside
it, named by backend (ADR 0007): `in_memory_literature_source` and `europe_pmc_literature_source` (S06).
Replaced the structural `ports.LiteratureSource` Protocol in S05b, so "who implements this?" is
one search and pyright checks every override. `retraction_status` (S12a) asks about exact ids, uncached
and without the citable filters, for the retraction re-check (ADR 0019).
Must not: hold any implementation, or import one.

No LLM is involved in this module.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.retrieval.models import RetractionStatus


class BaseLiteratureSource(ABC):
    """Searches a literature database for papers relevant to a question."""

    @abstractmethod
    def search(self, question: str, *, limit: int) -> tuple[Paper, ...]:
        """Find papers for `question`.

        Args:
            question: the research question, verbatim (non-blank, no control characters).
            limit: the maximum number of papers to return, in [1, 100].

        Returns:
            At most `limit` papers with unique source ids, in rank order. No hits: `()`, not an error.

        Raises:
            ValueError: bad input (`query.validate_search`), before any request.
            RetrievalError: the database failed or sent a malformed response.
            CacheMissError: read-only cache mode and the search is not cached.
        """

    @abstractmethod
    def retraction_status(self, source_ids: Sequence[SourceId]) -> tuple[RetractionStatus, ...]:
        """The current retraction status of each id, never from a cache.

        Args:
            source_ids: unique ids, any number (a backend splits them into requests as it must).

        Returns:
            One status per id, in input order; `retracted=None` for an id this source holds no record for.

        Raises:
            ValueError: duplicate ids, before any request.
            RetrievalError: the database failed, sent a malformed response, or answered for an id it was
                not asked about.
        """
