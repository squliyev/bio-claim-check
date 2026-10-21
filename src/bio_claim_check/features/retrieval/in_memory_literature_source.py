"""[RING:features/retrieval] An in-memory literature source over a fixed corpus (demos, tests, contracts).

Why: the walking skeleton (S05) and the offline demo need retrieval without a network. Every paper is
invented: compound names are fictional, ids live in the `FAKE:` namespace and no real PMID is used.
The raw abstracts carry the markup Europe PMC returns (`<i>`, `<sup>`, entities), so cleaning is
exercised end to end.
Must not: be wired into a live run, or contain any real paper.

No LLM is involved in this module.
"""

from typing import override

from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.retrieval.query import validate_search

FAKE_CORPUS: tuple[Paper, ...] = (
    Paper(
        source_id="FAKE:1",
        title="OS-912 lowers amyloid plaque load in APP/PS1 mice",
        year=2021,
        raw_abstract=(
            "<h4>Background</h4><p>OS-912 is a fictional plaque-binding compound.</p>"
            "<h4>Results</h4><p>In <i>APP/PS1</i> mice, OS-912 (10 mg/kg) reduced amyloid plaque load "
            "by 38% compared with vehicle (p &lt; 0.01). No cognitive outcomes were measured.</p>"
        ),
    ),
    Paper(
        source_id="FAKE:2",
        title="HX-15 in early cognitive decline: a fictional phase 2 trial",
        year=2022,
        raw_abstract=(
            "In a 52-week phase 2 trial of 120 patients, HX-15 did not significantly change cognitive "
            "scores (p = 0.41). Serum marker level fell from 4.1 &times; 10<sup>3</sup> to "
            "3.6 &times; 10<sup>3</sup> units."
        ),
    ),
    Paper(
        source_id="FAKE:3",
        title="OS-912 use and dementia incidence: a fictional retrospective cohort",
        year=2023,
        raw_abstract=(
            "Among 4,210 adults, OS-912 use was associated with a lower incidence of dementia "
            "(hazard ratio 0.81, 95% CI 0.70&ndash;0.94). Residual confounding cannot be excluded."
        ),
    ),
    Paper(
        source_id="FAKE:4",
        title="Plaque-targeting compounds: a fictional narrative review",
        year=2020,
        raw_abstract="Plaque-targeting compounds have shown mixed results in human trials.",
    ),
)
"""The whole fictional world, in rank order. Every id is `FAKE:<n>`."""


class InMemoryLiteratureSource(BaseLiteratureSource):
    """Returns the first `limit` papers of a fixed corpus, whatever the question."""

    def __init__(self, corpus: tuple[Paper, ...] = FAKE_CORPUS) -> None:
        self._corpus = corpus

    @override
    def search(self, question: str, *, limit: int) -> tuple[Paper, ...]:
        validate_search(question, limit)  # the same input contract as every backend
        return self._corpus[:limit]
