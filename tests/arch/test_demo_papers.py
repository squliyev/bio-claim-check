"""The H1 demo papers come from the predeclared rule: dev only, never test, never a paper already used."""

import pytest

from bio_claim_check.app.container import load_corpus_spec, read_dataset, sealed_test_ids
from bio_claim_check.features.contracts.corpus import CorpusSplit, SourceEntry
from bio_claim_check.features.corpus.layout import DEV_SOURCES, SPEC
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
