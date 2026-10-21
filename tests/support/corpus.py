"""[TEST SUPPORT] A fictional corpus world: a query-keyed literature source and the pools it serves.

`InMemoryLiteratureSource` ignores the query, but the corpus build sends one query per question, so
this source maps each exact query string to its ranked papers and records every call. The world is
built to exercise every corpus rule: a paper retrieved by two questions, an NCT id linking a dev-domain
paper to the held-out domain, a retracted paper and ids whose numeric and string orders differ.
"""

from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import override

from bio_claim_check.app.usecases.build_corpus import pool_query
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from tests.support.papers import paper

SPEC_FILE = Path(__file__).parents[1] / "fixtures" / "corpus" / "spec_valid.yaml"
CUTOFF = date(2024, 12, 31)


class QueryLiteratureSource(BaseLiteratureSource):
    """Serves fixed pools by exact query string; an unknown query returns no papers."""

    def __init__(self, pools: Mapping[str, tuple[Paper, ...]]) -> None:
        self._pools = dict(pools)
        self.calls: list[tuple[str, int]] = []

    @override
    def search(self, question: str, *, limit: int) -> tuple[Paper, ...]:
        self.calls.append((question, limit))
        return self._pools.get(question, ())[:limit]


ANIMAL = paper(1, mesh=("Animals", "Mice"))
COHORT = paper(2, mesh=("Humans", "Cohort Studies"))
STATIN_TRIAL = paper(3, abstract="We ran trial NCT01234567 in patients. The drug was tolerated.")
LINKED = paper(4, abstract="A secondary analysis of nct01234567 in patients. Results are reported.")
RETRACTED = paper(5, mesh=("Animals",), retracted=True)
NULL_RESULT = paper(10, abstract="Patients were randomised. The drug did not reduce decline.")
HEDGED = paper(11, abstract="Mice received the drug. Memory improved. These findings suggest a benefit.")


def world() -> dict[str, tuple[Paper, ...]]:
    """Ranked pools by query for the three questions in `spec_valid.yaml`."""
    return {
        pool_query("OS-912 AND decline", CUTOFF): (ANIMAL, COHORT, NULL_RESULT, RETRACTED, HEDGED),
        pool_query("OS-912 AND neurons", CUTOFF): (LINKED, ANIMAL),
        pool_query("HX-15 AND dementia", CUTOFF): (STATIN_TRIAL,),
    }
