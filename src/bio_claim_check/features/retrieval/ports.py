"""[RING:features/retrieval] The port retrieval owns: where citable papers come from.

Why: the use case depends on this interface, never on Europe PMC; a fake implements it now (S05) and
the Europe PMC adapter in S06.
Must not: hold any implementation.
"""

from typing import Protocol

from bio_claim_check.features.contracts.paper import Paper


class LiteratureSource(Protocol):
    """Searches a literature database for papers relevant to a question."""

    def search(self, question: str, *, limit: int) -> tuple[Paper, ...]:
        """At most `limit` papers with unique source ids, in rank order. No hits: `()`, not an error."""
        raise NotImplementedError
