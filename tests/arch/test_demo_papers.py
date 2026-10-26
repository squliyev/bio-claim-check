"""The H1 demo papers come from the predeclared rule: dev only, never test, never a paper already used."""

import json

import pytest

from bio_claim_check.app.container import default_rulepack, load_corpus_spec, read_dataset, sealed_test_ids
from bio_claim_check.features.contracts.corpus import CorpusSplit, SourceEntry
from bio_claim_check.features.corpus.layout import DEV_SOURCES, SPEC
from bio_claim_check.features.corpus.layout import SEALED as SEALED_FILE
from bio_claim_check.features.traps.validity import MAX_CLAIM_WORDS, contamination, pair_problems
from tests.support.demo_pick import KINDS, SHORTLIST, shortlist, used_ids
from tests.support.paths import ROOT, SEALED

pytestmark = pytest.mark.arch

PRIOR = used_ids(ROOT / "challenge" / "dev-v1.jsonl", ROOT / "traps" / "dev-v1.jsonl")


def _dev() -> list[SourceEntry]:
    lines = read_dataset(SEALED)[DEV_SOURCES].decode().splitlines()
    return [SourceEntry.model_validate_json(line) for line in lines]


def test_every_kind_has_a_full_dev_only_unused_shortlist() -> None:
    salt, closed, dev = load_corpus_spec(SEALED / SPEC).audit_salt, sealed_test_ids(SEALED), _dev()
    for kind, rule, _ in KINDS:
        picks = shortlist(dev, kind, rule, salt=salt, excluded=PRIOR)
        assert len(picks) == SHORTLIST, kind
        for e in picks:
            assert e.split is CorpusSplit.DEV
            assert not {e.source_id, e.cluster_id} & (closed | PRIOR)
            assert any(c.kind is kind and c.rule == rule for c in e.candidates)


def test_the_shortlist_ignores_input_order() -> None:
    salt, dev = load_corpus_spec(SEALED / SPEC).audit_salt, _dev()
    kind, rule, _ = KINDS[0]
    forward = shortlist(dev, kind, rule, salt=salt, excluded=PRIOR)
    assert shortlist(list(reversed(dev)), kind, rule, salt=salt, excluded=PRIOR) == forward


MANIFEST = ROOT / "demo" / "h1-trap-papers.json"


def test_the_picks_are_the_rule_s_first_eligible_papers_and_their_claims_are_usable() -> None:
    doc = json.loads(MANIFEST.read_text())
    spec, files = load_corpus_spec(SEALED / SPEC), read_dataset(SEALED)
    assert doc["dataset_seal"] == files[SEALED_FILE].decode().strip()
    assert doc["audit_salt"] == spec.audit_salt
    dev, pack = {e.source_id: e for e in _dev()}, default_rulepack()
    assert [(p["kind"], p["rule"], p["name"]) for p in doc["papers"]] == [
        (k.value, r, n) for k, r, n in KINDS
    ]
    for paper, (kind, rule, _) in zip(doc["papers"], KINDS, strict=True):
        ordered = [
            e.source_id for e in shortlist(dev.values(), kind, rule, salt=spec.audit_salt, excluded=PRIOR)
        ]
        assert [r["source_id"] for r in paper["rejected"]] == ordered[: paper["rank"] - 1]
        assert all(r["reason"].strip() for r in paper["rejected"])
        assert paper["source_id"] == ordered[paper["rank"] - 1]
        entry = dev[paper["source_id"]]
        assert (paper["cluster_id"], paper["abstract_sha256"]) == (entry.cluster_id, entry.abstract_sha256)
        for claim in (paper["faithful"], paper["overstated"]):
            assert len(claim.split()) <= MAX_CLAIM_WORDS
            assert not contamination(claim, pack)
        assert not pair_problems(paper["faithful"], paper["overstated"])


def test_the_manifest_carries_no_abstract_text() -> None:
    doc = json.loads(MANIFEST.read_text())
    keys = {k for p in doc["papers"] for k in p}
    assert not keys & {"abstract", "title", "text"}
