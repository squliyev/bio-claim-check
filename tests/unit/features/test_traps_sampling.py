"""Trap sampling (I78): dev only, scarce kinds first, one source per cluster, and top-ups extend the order."""

import pytest
from tests.support.corpus import source_entry

from bio_claim_check.features.contracts.corpus import CorpusSplit, QuestionRank, SourceEntry
from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.traps.sampling import TrapSamplingError, sample

PRE = OverstatedReason.PRECLINICAL_TO_CLINICAL
BG = OverstatedReason.BACKGROUND_AS_RESULT
QS = {"a-q1", "a-q2"}


def _with(entry: SourceEntry, **changes: object) -> SourceEntry:
    return SourceEntry.model_validate({**entry.model_dump(), **changes})


def test_only_dev_usable_sources_in_a_dev_pool_are_picked() -> None:
    entries = [
        source_entry(1),
        source_entry(2, CorpusSplit.TEST),
        _with(source_entry(3), ranks=(QuestionRank(question_id="b-q9", rank=1),)),
        _with(source_entry(4), ranks=(QuestionRank(question_id="a-q1", rank=50),)),
    ]
    picks = sample(entries, (PRE,), 1, questions=QS, max_rank=20)
    assert [p.source_id for p in picks] == ["MED:1"]


def test_the_question_is_the_best_rank_then_the_lowest_id() -> None:
    ranks = (QuestionRank(question_id="a-q1", rank=3), QuestionRank(question_id="a-q2", rank=2))
    tied = (QuestionRank(question_id="a-q1", rank=2), QuestionRank(question_id="a-q2", rank=2))
    assert (
        sample([_with(source_entry(1), ranks=ranks)], (PRE,), 1, questions=QS, max_rank=20)[0].question_id
        == "a-q2"
    )
    assert (
        sample([_with(source_entry(1), ranks=tied)], (PRE,), 1, questions=QS, max_rank=20)[0].question_id
        == "a-q1"
    )


def test_a_source_goes_to_its_scarcest_kind_and_is_used_once() -> None:
    both = source_entry(1, kinds=(PRE, BG))
    entries = [both, source_entry(2), source_entry(3)]
    picks = sample(entries, (PRE, BG), 1, questions=QS, max_rank=20)
    assert {(p.kind, p.source_id) for p in picks if p.kind is BG} == {(BG, "MED:1")}
    assert len({p.source_id for p in picks}) == len(picks)


def test_one_source_per_cluster() -> None:
    entries = [_with(source_entry(n), cluster_id="MED:1") for n in (1, 2, 3)]
    with pytest.raises(TrapSamplingError, match="1 eligible"):
        sample(entries, (PRE,), 2, questions=QS, max_rank=20)


def test_a_larger_per_kind_extends_the_earlier_picks() -> None:
    entries = [source_entry(n, kinds=(PRE, BG) if n % 3 == 0 else (PRE,)) for n in range(1, 30)]
    small = sample(entries, (BG, PRE), 3, questions=QS, max_rank=20)
    large = sample(entries, (BG, PRE), 6, questions=QS, max_rank=20)
    for kind in (BG, PRE):
        assert [p for p in large if p.kind is kind][:3] == [p for p in small if p.kind is kind]


def test_infeasible_targets_name_every_short_kind_and_per_kind_must_be_positive() -> None:
    with pytest.raises(TrapSamplingError) as err:
        sample([source_entry(1)], (PRE, BG), 2, questions=QS, max_rank=20)
    assert len(err.value.problems) == 2
    with pytest.raises(ValueError, match="at least 1"):
        sample([], (PRE,), 0, questions=QS, max_rank=20)
