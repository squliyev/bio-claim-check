"""[RING:features/retrieval] The port retrieval owns: where citable papers come from.

Why: the use case depends on this base, never on a backend. Implementations subclass it and sit beside
it, named by backend (ADR 0007): `in_memory_literature_source` and `europe_pmc_literature_source` (S06).
Replaced the structural `ports.LiteratureSource` Protocol in S05b, so "who implements this?" is
one search and pyright checks every override.
Must not: hold any implementation, or import one.

No LLM is involved in this module.
"""

from abc import ABC, abstractmethod

from bio_claim_check.features.contracts.paper import Paper


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
