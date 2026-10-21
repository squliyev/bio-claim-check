"""Cluster split (ADR 0010): the same trial or the same paper never lands in both dev and test."""

import pytest
from tests.support.papers import paper

from bio_claim_check.features.contracts.corpus import CorpusSplit
from bio_claim_check.features.corpus.clusters import (
    assign_splits,
    clusters,
    hash_fraction,
    id_order,
    registry_ids,
    title_key,
)


def test_registry_ids_are_case_insensitive_and_upper_cased() -> None:
    p = paper(title="Trial nct01234567 report", abstract="Registered as NCT07654321 and NCT01234567.")
    assert registry_ids(p) == frozenset({"NCT01234567", "NCT07654321"})


@pytest.mark.parametrize("text", ["NCT0123456", "NCT012345678", "xNCT01234567", "NCT 01234567"])
def test_malformed_registry_ids_are_ignored(text: str) -> None:
    assert registry_ids(paper(abstract=f"Registered as {text}.")) == frozenset()


def test_title_key_ignores_case_punctuation_and_spacing() -> None:
    assert title_key("Metformin & Cancer: A_Cohort.") == title_key("metformin cancer a cohort") != ""
    assert title_key("—") == ""


def test_id_order_is_numeric_within_a_namespace() -> None:
    ids = ["MED:10", "FAKE:x", "MED:9", "FAKE:2"]
    assert sorted(ids, key=id_order) == ["FAKE:2", "FAKE:x", "MED:9", "MED:10"]


def test_chain_through_nct_and_title_is_one_cluster_with_the_smallest_id() -> None:
    a = paper(10, abstract="Results of NCT01234567 are reported here.")
    b = paper(9, title="Shared title", abstract="Follow-up of nct01234567.")
    c = paper(30, title="SHARED   title!")
    d = paper(4)
    assert clusters([a, b, c, d]) == {
        "MED:10": "MED:9",
        "MED:9": "MED:9",
        "MED:30": "MED:9",
        "MED:4": "MED:4",
    }


def test_one_paper_with_two_trial_ids_joins_both_trials() -> None:
    a = paper(5, abstract="Part of NCT00000001.")
    b = paper(6, abstract="Part of NCT00000002.")
    bridge = paper(7, abstract="Pooled NCT00000001 and NCT00000002.")
    assert set(clusters([a, b, bridge]).values()) == {"MED:5"}


def test_clusters_do_not_depend_on_input_order() -> None:
    papers = [paper(n, abstract=f"Trial NCT0000000{n % 3}.") for n in range(1, 13)]
    expected = clusters(papers)
    for shift in range(1, len(papers)):
        assert clusters(papers[shift:] + papers[:shift]) == expected
    assert clusters(papers[::-1]) == expected


def test_hash_fraction_is_stable_and_in_range() -> None:
    value = hash_fraction("bio-claim-check/split/v1", "MED:1")
    assert 0 <= value < 1
    assert value == hash_fraction("bio-claim-check/split/v1", "MED:1")
    assert value != hash_fraction("other-salt", "MED:1")


def test_held_out_cluster_goes_to_test_even_when_its_hash_says_dev() -> None:
    cluster_of = {"MED:1": "MED:1", "MED:2": "MED:1"}
    dev = assign_splits(cluster_of, (), salt="s", dev_fraction=0.999999)
    assert set(dev.values()) == {CorpusSplit.DEV}
    held = assign_splits(cluster_of, ["MED:2"], salt="s", dev_fraction=0.999999)
    assert held == {"MED:1": CorpusSplit.TEST, "MED:2": CorpusSplit.TEST}


def test_split_follows_the_hash_threshold_per_cluster() -> None:
    ids = [f"MED:{n}" for n in range(1, 201)]
    cluster_of = {s: s for s in ids}
    split = assign_splits(cluster_of, (), salt="s", dev_fraction=0.5)
    for s in ids:
        assert (split[s] is CorpusSplit.DEV) == (hash_fraction("s", s) < 0.5)
    assert 60 < sum(v is CorpusSplit.DEV for v in split.values()) < 140
