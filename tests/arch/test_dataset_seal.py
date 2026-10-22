"""The committed dataset is intact and sealed, and nothing outside it names a sealed-test source (I41)."""

from pathlib import Path

import pytest

from bio_claim_check.app.container import load_corpus_spec, read_dataset
from bio_claim_check.features.contracts.corpus import CorpusSplit, SourceEntry
from bio_claim_check.features.corpus.layout import SPEC, sources_file
from bio_claim_check.features.corpus.seal import dataset_problems
from tests.support.guards import check_no_test_ids
from tests.support.paths import ROOT
from tests.support.project_files import repo_files

pytestmark = pytest.mark.arch

DATASET = ROOT / "datasets"
PMIDS = frozenset({"31234567", "29876543"})
QIDS = frozenset({"fx-statin-q1", "fx-glp1-q4"})
# Pinned outside datasets/, so editing the data, re-hashing the manifest and re-sealing cannot stay green:
# a new seal is a visible diff in this file. SEALED hashes manifest.json, which hashes corpus.yaml and
# every data file, so this one value pins them all.
EXPECTED_SEAL = "fd519195e96bdff2d4b7665c2f2c57acaf05d6efa89cc8d690bd18d45ce27fb5"


def _check(text: str) -> list[str]:
    return [v.detail for v in check_no_test_ids(Path("x"), text, test_pmids=PMIDS, test_question_ids=QIDS)]


@pytest.mark.parametrize(
    "text",
    [
        "dev source MED:30000001 and 2024-12-31",
        "a longer number 312345678 and a prefix 3123456",
        "version 31234567.1, 1.31234567 and id fx-statin-q10 and glp1-q4b",
        "x_statin-q1 is another word",
    ],
)
def test_no_test_ids_guard_accepts(text: str) -> None:
    assert _check(text) == []


@pytest.mark.parametrize(
    ("text", "detail"),
    [
        ("cites MED:31234567 here", "test PMID 31234567"),
        ("PMID 29876543.", "test PMID 29876543"),
        ('{"id": "fx-statin-q1"}', "test question id fx-statin-q1"),
        ("see fx-glp1-q4, then", "test question id fx-glp1-q4"),
        ("PMID31234567 and MED31234567", "test PMID 31234567"),
        ("pmid_29876543", "test PMID 29876543"),
    ],
)
def test_no_test_ids_guard_rejects(text: str, detail: str) -> None:
    assert detail in _check(text)


def test_no_test_ids_guard_scans_the_path() -> None:
    found = check_no_test_ids(
        Path("docs/notes-31234567.md"), "clean", test_pmids=PMIDS, test_question_ids=QIDS
    )
    assert [(v.line, v.detail) for v in found] == [(0, "test PMID 31234567")]


def _text_files() -> list[Path]:
    texts: list[Path] = []
    for path in repo_files(ROOT):
        if path.relative_to(ROOT).parts[0] == "datasets":
            continue
        path.read_text(encoding="utf-8")  # fail closed: a non-UTF-8 tracked file would hide ids from the scan
        texts.append(path)
    return texts


# Keyed on build outputs, not the spec: the pre-registration commit holds corpus.yaml alone. Any one output
# present runs the checks, so a partial dataset (e.g. no SEALED) fails instead of skipping.
BUILD_OUTPUTS = ("manifest.json", "SEALED")
needs_dataset = pytest.mark.skipif(
    not any((DATASET / name).exists() for name in BUILD_OUTPUTS), reason="datasets/ not built yet (S07b)"
)


@needs_dataset
def test_the_committed_dataset_is_intact_and_sealed() -> None:
    spec = load_corpus_spec(DATASET / SPEC)
    assert dataset_problems(read_dataset(DATASET), spec) == []


@needs_dataset
def test_the_seal_is_the_pinned_one() -> None:
    assert (DATASET / "SEALED").read_text(encoding="ascii").strip() == EXPECTED_SEAL


@needs_dataset
def test_no_tracked_file_outside_datasets_names_a_test_id() -> None:
    spec = load_corpus_spec(DATASET / SPEC)
    test_file = DATASET / sources_file(CorpusSplit.TEST)
    rows = [
        SourceEntry.model_validate_json(line) for line in test_file.read_text(encoding="utf-8").splitlines()
    ]
    pmids = frozenset(r.source_id.removeprefix("MED:") for r in rows)
    qids = frozenset(q.id for q in spec.questions if q.split is CorpusSplit.TEST)
    files = _text_files()
    assert files
    found = [
        v
        for f in files
        for v in check_no_test_ids(f, f.read_text(encoding="utf-8"), test_pmids=pmids, test_question_ids=qids)
    ]
    assert found == []
