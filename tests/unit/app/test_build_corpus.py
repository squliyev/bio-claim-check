"""`build_corpus`: deterministic dataset bytes from a spec and a (fictional) literature source.

The golden files pin the exact bytes (I37); the other tests state each rule on its own so a golden
update can never silently bless a broken rule.
"""

import json
from pathlib import Path

import pytest
from tests.support.corpus import (
    ANIMAL,
    CUTOFF,
    FETCHED,
    HEDGED,
    LINKED,
    SPEC_FILE,
    STATIN_TRIAL,
    QueryLiteratureSource,
    build,
    world,
)
from tests.support.papers import paper

from bio_claim_check.app.container import load_corpus_spec
from bio_claim_check.app.usecases.build_corpus import (
    CorpusFiles,
    PoolConflictError,
    pool_query,
)
from bio_claim_check.features.contracts.corpus import (
    NLM_NOTICE,
    CorpusManifest,
    CorpusSpec,
    CorpusSplit,
    NeverReason,
    SourceEntry,
)
from bio_claim_check.features.corpus.clusters import hash_fraction
from bio_claim_check.features.corpus.layout import DEV_SOURCES, QUESTIONS, TEST_SOURCES
from bio_claim_check.features.corpus.serialise import model_sha256, sha256_hex

pytestmark = pytest.mark.unit
GOLDEN = Path(__file__).parents[2] / "fixtures" / "corpus" / "golden"


def rows(data: bytes) -> list[SourceEntry]:
    return [SourceEntry.model_validate_json(line) for line in data.splitlines()]


def all_rows(files: CorpusFiles) -> dict[str, SourceEntry]:
    return {e.source_id: e for name in (DEV_SOURCES, TEST_SOURCES) for e in rows(files.data[name])}


def test_bytes_match_the_golden_files(update_golden: bool) -> None:
    files = build()
    produced = {
        "dev_sources.jsonl": files.data[DEV_SOURCES],
        "test_sources.jsonl": files.data[TEST_SOURCES],
        "questions.jsonl": files.data[QUESTIONS],
        "manifest.json": files.manifest,
    }
    if update_golden:
        GOLDEN.mkdir(parents=True, exist_ok=True)
        for name, data in produced.items():
            (GOLDEN / name).write_bytes(data)
        pytest.fail("rewrote the corpus golden files; review the diff and rerun without --update-golden")
    for name, data in produced.items():
        assert data == (GOLDEN / name).read_bytes(), name


def test_rebuild_is_byte_identical() -> None:
    assert build() == build()


def test_question_order_in_the_spec_does_not_change_the_data() -> None:
    spec = load_corpus_spec(SPEC_FILE)
    data = spec.model_dump()
    reordered = CorpusSpec.model_validate({**data, "questions": list(reversed(data["questions"]))})
    assert build(reordered).data == build(spec).data
    assert build(reordered).manifest != build(spec).manifest  # the spec is hashed as written


def test_rank_order_within_a_pool_is_data() -> None:
    reranked = {q: tuple(reversed(pool)) for q, pool in world().items()}
    assert build(source=QueryLiteratureSource(reranked)).data != build().data


def test_each_question_is_searched_once_with_its_cutoff_and_pool_size() -> None:
    source = QueryLiteratureSource(world())
    build(source=source)
    assert source.calls == [
        ("(OS-912 AND decline) AND FIRST_PDATE:[1900-01-01 TO 2024-12-31]", 100),
        ("(OS-912 AND neurons) AND FIRST_PDATE:[1900-01-01 TO 2024-12-31]", 100),
        ("(HX-15 AND dementia) AND FIRST_PDATE:[1900-01-01 TO 2024-12-31]", 100),
    ]


def test_a_source_retrieved_by_two_questions_is_one_row_with_both_ranks() -> None:
    entry = all_rows(build())[ANIMAL.source_id]
    assert [(r.question_id, r.rank) for r in entry.ranks] == [("fx-glp1-q1", 1), ("fx-glp1-q2", 2)]


def test_held_out_sources_and_their_cluster_are_in_test() -> None:
    spec = load_corpus_spec(SPEC_FILE)
    assert hash_fraction(spec.split_salt, STATIN_TRIAL.source_id) < spec.dev_fraction  # hash alone says dev
    entries = all_rows(build())
    assert entries[STATIN_TRIAL.source_id].split is CorpusSplit.TEST
    assert entries[LINKED.source_id].cluster_id == STATIN_TRIAL.source_id
    assert entries[LINKED.source_id].split is CorpusSplit.TEST


def test_no_cluster_spans_both_splits() -> None:
    files = build()
    dev = {e.cluster_id for e in rows(files.data[DEV_SOURCES])}
    test = {e.cluster_id for e in rows(files.data[TEST_SOURCES])}
    assert dev.isdisjoint(test)


def test_retracted_sources_stay_in_the_pool_but_are_never_candidates() -> None:
    entry = all_rows(build())["MED:5"]
    assert entry.retracted
    assert entry.never_because == (NeverReason.RETRACTED,)
    assert entry.candidates == ()


def test_rows_are_in_numeric_id_order() -> None:
    files = build()
    for name in (DEV_SOURCES, TEST_SOURCES):
        ids = [int(e.source_id.removeprefix("MED:")) for e in rows(files.data[name])]
        assert ids == sorted(ids)


def test_questions_record_their_query_and_pool() -> None:
    questions = [json.loads(line) for line in build().data[QUESTIONS].splitlines()]
    assert [q["id"] for q in questions] == ["fx-glp1-q1", "fx-glp1-q2", "fx-statin-q1"]
    by_id = {q["id"]: q for q in questions}
    assert by_id["fx-glp1-q1"]["query"] == pool_query("OS-912 AND decline", CUTOFF)
    assert [q["pool_size"] for q in questions] == [5, 2, 1]


def test_dev_holds_a_candidate_source() -> None:
    entry = rows(build().data[DEV_SOURCES])
    assert {e.source_id for e in entry} == {"MED:5", HEDGED.source_id}
    hedged = next(e for e in entry if e.source_id == HEDGED.source_id)
    assert [c.kind for c in hedged.candidates] == ["certainty_inflation"]


def test_an_empty_pool_is_recorded_not_topped_up() -> None:
    pools = world()
    pools[pool_query("HX-15 AND dementia", CUTOFF)] = ()
    files = build(source=QueryLiteratureSource(pools))
    questions = [json.loads(line) for line in files.data[QUESTIONS].splitlines()]
    assert {q["id"]: q["pool_size"] for q in questions}["fx-statin-q1"] == 0


def questions_by_id(files: CorpusFiles) -> dict[str, dict[str, object]]:
    return {q["id"]: q for q in map(json.loads, files.data[QUESTIONS].splitlines())}


def test_each_question_counts_only_the_pool_sources_in_its_own_split() -> None:
    pools = world()
    neurons = pool_query("OS-912 AND neurons", CUTOFF)
    pools[neurons] = (HEDGED, *pools[neurons])  # HEDGED is a dev source; fx-glp1-q2 is a test question
    by_id = questions_by_id(build(source=QueryLiteratureSource(pools)))
    assert (by_id["fx-glp1-q2"]["pool_size"], by_id["fx-glp1-q2"]["split_pool_size"]) == (3, 2)
    assert (by_id["fx-glp1-q1"]["pool_size"], by_id["fx-glp1-q1"]["split_pool_size"]) == (5, 2)


def test_response_hash_comes_from_the_source_for_the_exact_query() -> None:
    source = QueryLiteratureSource(world())
    by_id = questions_by_id(build(source=source))
    query = pool_query("OS-912 AND decline", CUTOFF)
    assert by_id["fx-glp1-q1"]["response_sha256"] == source.response_sha256(query, 100)


def test_a_changed_response_changes_its_hash_and_no_other() -> None:
    before = questions_by_id(build())
    pools = world()
    pools[pool_query("HX-15 AND dementia", CUTOFF)] = ()
    after = questions_by_id(build(source=QueryLiteratureSource(pools)))
    changed = {q for q in before if before[q]["response_sha256"] != after[q]["response_sha256"]}
    assert changed == {"fx-statin-q1"}


def test_manifest_records_the_raw_spec_file_hash() -> None:
    manifest = CorpusManifest.model_validate_json(build().manifest)
    assert manifest.spec_file_sha256 == sha256_hex(SPEC_FILE.read_bytes())


def test_manifest_hashes_every_data_file_and_the_spec() -> None:
    files = build()
    manifest = CorpusManifest.model_validate_json(files.manifest)
    assert {f.name: f.sha256 for f in manifest.files} == {n: sha256_hex(b) for n, b in files.data.items()}
    assert manifest.spec_sha256 == model_sha256(load_corpus_spec(SPEC_FILE))
    assert manifest.notice == NLM_NOTICE
    assert manifest.declared_fetched_on == FETCHED


def test_candidate_counts_include_zeros_for_every_cell() -> None:
    spec = load_corpus_spec(SPEC_FILE)
    counts = CorpusManifest.model_validate_json(build().manifest).candidate_counts
    assert len(counts) == len(spec.domains) * len(CorpusSplit) * len(spec.trap_kinds)
    assert any(c.n == 0 for c in counts)
    assert sum(c.n for c in counts) > 0


def test_a_source_in_two_domains_counts_in_each() -> None:
    shared = paper(7, mesh=("Animals",))
    pools = world()
    pools[pool_query("OS-912 AND decline", CUTOFF)] = (shared,)
    pools[pool_query("OS-912 AND neurons", CUTOFF)] = ()
    pools[pool_query("HX-15 AND dementia", CUTOFF)] = (shared,)
    counts = CorpusManifest.model_validate_json(build(source=QueryLiteratureSource(pools)).manifest)
    preclinical = {
        (c.domain, c.split): c.n for c in counts.candidate_counts if c.kind == "preclinical_to_clinical"
    }
    assert preclinical[("glp1-neuro", CorpusSplit.TEST)] == 1
    assert preclinical[("statin-neuro", CorpusSplit.TEST)] == 1


def test_conflicting_metadata_for_one_source_stops_the_build() -> None:
    pools = world()
    pools[pool_query("OS-912 AND neurons", CUTOFF)] = (paper(1, mesh=("Humans",)),)
    with pytest.raises(PoolConflictError, match="MED:1"):
        build(source=QueryLiteratureSource(pools))
