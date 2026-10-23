"""Dev pool: only the question's own dev sources with matching hashes, in rank order; every drop counted."""

import pytest
from tests.support.corpus import HEDGED, RETRACTED, dataset_files, world
from tests.support.papers import paper

from bio_claim_check.features.contracts.corpus import QuestionEntry, SourceEntry
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.corpus.dev_pool import DevPool, DropReason, dev_pool
from bio_claim_check.features.corpus.layout import DEV_SOURCES, QUESTIONS, TEST_SOURCES

pytestmark = pytest.mark.unit

FILES = dataset_files()
# fx-glp1-q1 is the fixture's only dev question: MED:5 (rank 4) and MED:11 (rank 5) are its dev pool;
# MED:1, MED:2 and MED:10 are in its pool but in the test split.
QUESTION = next(
    q
    for q in map(QuestionEntry.model_validate_json, FILES[QUESTIONS].decode().splitlines())
    if q.id == "fx-glp1-q1"
)
ENTRIES = [
    SourceEntry.model_validate_json(line)
    for name in (DEV_SOURCES, TEST_SOURCES)
    for line in FILES[name].decode().splitlines()
]
FETCHED = next(iter(world().values()))  # ANIMAL, COHORT, NULL_RESULT, RETRACTED, HEDGED


def _pool(fetched: tuple[Paper, ...] = FETCHED, k: int = 8) -> DevPool:
    return dev_pool(QUESTION, ENTRIES, fetched, k)


def _drops(**counts: int) -> dict[DropReason, int]:
    return {reason: counts.get(reason.value, 0) for reason in DropReason}


def test_keeps_only_dev_sources_and_counts_test_sources_as_not_dev() -> None:
    pool = _pool()
    assert [p.source_id for p in pool.papers] == ["MED:5", "MED:11"]
    assert pool.usable == 2
    assert pool.dropped == _drops(not_dev=3)


def test_orders_by_recorded_rank_not_by_fetch_order() -> None:
    assert [p.source_id for p in _pool(tuple(reversed(FETCHED))).papers] == ["MED:5", "MED:11"]


def test_k_cuts_the_papers_but_not_the_usable_count() -> None:
    pool = _pool(k=1)
    assert [p.source_id for p in pool.papers] == ["MED:5"]
    assert pool.usable == 2
    assert pool.dropped == _drops(not_dev=3, beyond_k=1)


def test_a_source_outside_the_pool_is_dropped() -> None:
    assert _pool((*FETCHED, paper(99))).dropped == _drops(not_dev=3, not_in_pool=1)


def test_a_changed_abstract_is_dropped_as_hash_drift() -> None:
    drifted = tuple(
        paper(11, abstract="A different text. It may help.") if p is HEDGED else p for p in FETCHED
    )
    pool = _pool(drifted)
    assert [p.source_id for p in pool.papers] == ["MED:5"]
    assert pool.dropped == _drops(not_dev=3, hash_drift=1)


def test_an_expected_dev_source_that_was_not_fetched_is_counted() -> None:
    pool = _pool(tuple(p for p in FETCHED if p is not RETRACTED))
    assert [p.source_id for p in pool.papers] == ["MED:11"]
    assert pool.dropped == _drops(not_dev=3, missing_expected=1)


def test_nothing_fetched_counts_every_expected_dev_source() -> None:
    pool = _pool(())
    assert (pool.papers, pool.usable) == ((), 0)
    assert pool.dropped == _drops(missing_expected=2)


@pytest.mark.parametrize("k", [0, 1.5, "8", True])
def test_a_bad_k_is_refused(k: int) -> None:
    with pytest.raises(ValueError, match="k must be a positive int"):
        _pool(k=k)
