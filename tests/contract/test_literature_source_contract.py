"""Shared literature-source contract: every `BaseLiteratureSource` passes the same scenarios (I33, I35)."""

from collections.abc import Callable

import pytest

from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.retrieval.europe_pmc_literature_source import EuropePmcLiteratureSource
from bio_claim_check.features.retrieval.in_memory_literature_source import (
    FAKE_CORPUS,
    InMemoryLiteratureSource,
)
from tests.support.europepmc import envelope, harness, mixed_records, ok

pytestmark = pytest.mark.contract

IMPLEMENTATIONS: tuple[type[BaseLiteratureSource], ...] = (
    EuropePmcLiteratureSource,
    InMemoryLiteratureSource,
)
"""Must equal the discovered implementations (I33, enforced in tests/arch/test_port_guards.py)."""


def _europe_pmc(records: int) -> BaseLiteratureSource:
    """A backend whose server answers every request with `records` of the fictional mixed fixture."""
    body = envelope(mixed_records()[:records]) if records else envelope([])
    return harness(*(ok(body) for _ in range(5))).source


_FACTORIES: dict[type[BaseLiteratureSource], Callable[[int], BaseLiteratureSource]] = {
    EuropePmcLiteratureSource: _europe_pmc,
    InMemoryLiteratureSource: lambda n: InMemoryLiteratureSource(FAKE_CORPUS[:n]),
}


@pytest.fixture(params=IMPLEMENTATIONS, ids=lambda c: c.__name__)
def make(request: pytest.FixtureRequest) -> Callable[[int], BaseLiteratureSource]:
    return _FACTORIES[request.param]


@pytest.mark.parametrize("limit", [1, 2, 3, 100])
def test_at_most_limit_unique_papers(make: Callable[[int], BaseLiteratureSource], limit: int) -> None:
    papers = make(4).search("plaque", limit=limit)
    assert 1 <= len(papers) <= limit
    assert len({p.source_id for p in papers}) == len(papers)


def test_same_input_same_order(make: Callable[[int], BaseLiteratureSource]) -> None:
    source = make(4)
    assert source.search("plaque", limit=10) == source.search("plaque", limit=10)


def test_no_hits_is_empty(make: Callable[[int], BaseLiteratureSource]) -> None:
    assert make(0).search("plaque", limit=5) == ()


@pytest.mark.parametrize(("question", "limit"), [("", 5), (" \t", 5), ("ok", 0), ("ok", 101), ("a\nb", 5)])
def test_bad_input_is_a_value_error(
    make: Callable[[int], BaseLiteratureSource], question: str, limit: int
) -> None:
    with pytest.raises(ValueError, match=r"question|limit"):
        make(4).search(question, limit=limit)


def test_real_ids_are_medline_ids(make: Callable[[int], BaseLiteratureSource]) -> None:
    """I35: anything not in the fictional `FAKE:` namespace is `MED:<digits>`."""
    for paper in make(10).search("a) OR (b", limit=100):
        if not paper.source_id.startswith("FAKE:"):
            namespace, _, pmid = paper.source_id.partition(":")
            assert (namespace, pmid.isdigit()) == ("MED", True)
