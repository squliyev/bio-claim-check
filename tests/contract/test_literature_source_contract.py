"""Shared literature-source contract: every `BaseLiteratureSource` passes the same scenarios (I33, I35)."""

from collections.abc import Callable

import pytest

from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.retrieval.errors import PaperNotFoundError
from bio_claim_check.features.retrieval.europe_pmc_literature_source import EuropePmcLiteratureSource
from bio_claim_check.features.retrieval.in_memory_literature_source import (
    FAKE_CORPUS,
    InMemoryLiteratureSource,
)
from bio_claim_check.features.retrieval.models import RetractionStatus
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


STATUS = {"MED:90000001": False, "MED:90000004": True}
"""What each source holds: one current paper, one retracted. `MED:90000077` is held by neither."""


def _europe_pmc_status() -> BaseLiteratureSource:
    held = [r for r in mixed_records() if f"MED:{r.get('pmid')}" in STATUS and r.get("source") == "MED"]
    return harness(ok(envelope(held[:2]))).source


def _in_memory_status() -> BaseLiteratureSource:
    return InMemoryLiteratureSource(
        tuple(
            Paper(source_id=s, title="T", year=2020, raw_abstract="A.", retracted=r)
            for s, r in STATUS.items()
        )
    )


_STATUS_FACTORIES: dict[type[BaseLiteratureSource], Callable[[], BaseLiteratureSource]] = {
    EuropePmcLiteratureSource: _europe_pmc_status,
    InMemoryLiteratureSource: _in_memory_status,
}


@pytest.fixture(params=IMPLEMENTATIONS, ids=lambda c: c.__name__)
def status_source(request: pytest.FixtureRequest) -> BaseLiteratureSource:
    return _STATUS_FACTORIES[request.param]()


def test_retraction_status_is_one_row_per_id_in_input_order(status_source: BaseLiteratureSource) -> None:
    ids = ("MED:90000077", "MED:90000004", "MED:90000001")
    assert status_source.retraction_status(ids) == (
        RetractionStatus(source_id="MED:90000077", retracted=None),
        RetractionStatus(source_id="MED:90000004", retracted=True),
        RetractionStatus(source_id="MED:90000001", retracted=False),
    )


def test_retraction_status_of_nothing_is_empty(status_source: BaseLiteratureSource) -> None:
    assert status_source.retraction_status(()) == ()


def test_duplicate_retraction_ids_are_a_value_error(status_source: BaseLiteratureSource) -> None:
    with pytest.raises(ValueError, match="unique"):
        status_source.retraction_status(("MED:90000001", "MED:90000001"))


# ---------------------------------------------------------------- fetch (S17a, ADR 0025)

FETCH_IDS: dict[type[BaseLiteratureSource], tuple[str, str, str]] = {
    EuropePmcLiteratureSource: ("MED:90000001", "MED:90000077", "FAKE:1"),
    InMemoryLiteratureSource: ("FAKE:1", "FAKE:77", "MED:90000001"),
}
"""(held, not held, another source's scheme) for each implementation."""


def _europe_pmc_fetch(source_id: str) -> BaseLiteratureSource:
    pmid = source_id.removeprefix("MED:")
    held = [r for r in mixed_records() if r.get("pmid") == pmid and r.get("source") == "MED"][:1]
    return harness(ok(envelope(held))).source


_FETCH_FACTORIES: dict[type[BaseLiteratureSource], Callable[[str], BaseLiteratureSource]] = {
    EuropePmcLiteratureSource: _europe_pmc_fetch,
    InMemoryLiteratureSource: lambda _: InMemoryLiteratureSource(),
}


@pytest.fixture(params=IMPLEMENTATIONS, ids=lambda c: c.__name__)
def fetch_impl(request: pytest.FixtureRequest) -> type[BaseLiteratureSource]:
    return request.param


def test_fetch_returns_the_paper_with_exactly_that_id(fetch_impl: type[BaseLiteratureSource]) -> None:
    held, _, _ = FETCH_IDS[fetch_impl]
    paper = _FETCH_FACTORIES[fetch_impl](held).fetch(held)
    assert paper.source_id == held
    assert paper.abstract


def test_fetch_of_an_unheld_id_is_not_found(fetch_impl: type[BaseLiteratureSource]) -> None:
    _, missing, _ = FETCH_IDS[fetch_impl]
    with pytest.raises(PaperNotFoundError) as caught:
        _FETCH_FACTORIES[fetch_impl](missing).fetch(missing)
    assert caught.value.source_id == missing


def test_fetch_of_another_scheme_is_a_value_error(fetch_impl: type[BaseLiteratureSource]) -> None:
    _, _, foreign = FETCH_IDS[fetch_impl]
    with pytest.raises(ValueError, match=r"fetch|holds only"):
        _FETCH_FACTORIES[fetch_impl](foreign).fetch(foreign)
