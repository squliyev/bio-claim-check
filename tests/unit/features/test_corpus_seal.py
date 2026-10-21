"""`dataset_problems`: an intact dataset gives [], and each kind of tampering gives its own named problem."""

import json

import pytest
from tests.support.corpus import SPEC_FILE, dataset_files

from bio_claim_check.app.container import load_corpus_spec
from bio_claim_check.features.contracts.corpus import (
    AuditDecision,
    AuditRecord,
    CorpusSpec,
    CorpusSplit,
    SourceEntry,
)
from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.corpus.audit_sheet import audit_ids
from bio_claim_check.features.corpus.layout import (
    DEV_SOURCES,
    MANIFEST,
    QUESTIONS,
    README,
    SEALED,
    SPEC,
    TEST_SOURCES,
    audit_file,
    sources_file,
)
from bio_claim_check.features.corpus.seal import dataset_problems, sealed_bytes
from bio_claim_check.features.corpus.serialise import document_bytes, sha256_hex

pytestmark = pytest.mark.unit
SPEC_MODEL = load_corpus_spec(SPEC_FILE)


def sealed() -> dict[str, bytes]:
    files = dataset_files()
    return {**files, SEALED: sealed_bytes(files[MANIFEST])}


def entries(files: dict[str, bytes]) -> list[SourceEntry]:
    return [
        SourceEntry.model_validate_json(line)
        for name in (DEV_SOURCES, TEST_SOURCES)
        for line in files[name].splitlines()
    ]


def rehash(files: dict[str, bytes]) -> dict[str, bytes]:
    """Re-sign the manifest after editing a data file, as a careful tamperer would."""
    manifest = json.loads(files[MANIFEST])
    for f in manifest["files"]:
        f["sha256"] = sha256_hex(files[f["name"]])
    files[MANIFEST] = json.dumps(manifest, indent=2).encode() + b"\n"
    files[SEALED] = sealed_bytes(files[MANIFEST])
    return files


def test_an_intact_dataset_has_no_problems() -> None:
    assert dataset_problems(sealed(), SPEC_MODEL) == []


def test_sealed_bytes_is_the_manifest_hash_and_a_newline() -> None:
    assert sealed_bytes(b"x") == (sha256_hex(b"x") + "\n").encode()


def test_unsealed_is_fine_only_when_the_seal_is_not_required() -> None:
    files = dataset_files()
    assert dataset_problems(files, SPEC_MODEL, require_seal=False) == []
    assert dataset_problems(files, SPEC_MODEL) == [f"{SEALED} is missing"]


def test_a_wrong_seal_is_a_problem_even_when_not_required() -> None:
    files = {**dataset_files(), SEALED: b"0" * 64 + b"\n"}
    assert dataset_problems(files, SPEC_MODEL, require_seal=False) == [f"{SEALED} does not match {MANIFEST}"]


def test_a_missing_manifest_stops_the_check() -> None:
    files = sealed()
    del files[MANIFEST]
    assert dataset_problems(files, SPEC_MODEL) == [f"{MANIFEST} is missing"]


@pytest.mark.parametrize("name", [SPEC, QUESTIONS, DEV_SOURCES, TEST_SOURCES])
def test_a_missing_file_is_named(name: str) -> None:
    files = sealed()
    del files[name]
    assert dataset_problems(files, SPEC_MODEL) == [f"{name} is missing"]


def test_an_unparseable_manifest_is_a_problem() -> None:
    files = sealed()
    files[MANIFEST] = b"{}"
    files[SEALED] = sealed_bytes(files[MANIFEST])
    problems = dataset_problems(files, SPEC_MODEL)
    assert len(problems) == 1
    assert problems[0].startswith(f"{MANIFEST}: ")


@pytest.mark.parametrize("name", [QUESTIONS, DEV_SOURCES, TEST_SOURCES])
def test_an_edited_data_file_breaks_its_hash(name: str) -> None:
    files = sealed()
    files[name] = files[name][:-1] + b" \n"  # still valid JSON, different bytes
    assert dataset_problems(files, SPEC_MODEL) == [f"{name} does not match its hash in {MANIFEST}"]


def test_an_edited_manifest_breaks_the_seal() -> None:
    files = sealed()
    files[MANIFEST] += b" "
    assert dataset_problems(files, SPEC_MODEL) == [f"{SEALED} does not match {MANIFEST}"]


def test_an_edited_spec_file_breaks_its_hash() -> None:
    files = sealed()
    files[SPEC] += b"# edited\n"
    assert dataset_problems(files, SPEC_MODEL) == [f"{SPEC} does not match spec_file_sha256 in {MANIFEST}"]


def test_a_different_parsed_spec_is_a_problem() -> None:
    other = CorpusSpec.model_validate({**SPEC_MODEL.model_dump(), "audit_n": SPEC_MODEL.audit_n + 1})
    assert dataset_problems(sealed(), other) == [f"the parsed spec does not match spec_sha256 in {MANIFEST}"]


def test_the_manifest_must_hash_exactly_the_data_files() -> None:
    files = sealed()
    manifest = json.loads(files[MANIFEST])
    manifest["files"] = manifest["files"][:-1]
    files[MANIFEST] = json.dumps(manifest).encode()
    files[SEALED] = sealed_bytes(files[MANIFEST])
    assert any("must hash exactly" in p for p in dataset_problems(files, SPEC_MODEL))


def test_an_extra_file_is_named_and_readme_and_audits_are_allowed() -> None:
    files = {**sealed(), "notes.txt": b"x", README: b"# data\n"}
    assert dataset_problems(files, SPEC_MODEL) == ["notes.txt is not part of the dataset"]


def test_a_row_in_the_wrong_split_file_is_a_problem() -> None:
    files = sealed()
    dev = files[DEV_SOURCES].splitlines(keepends=True)
    files[TEST_SOURCES] += dev[0]
    files[DEV_SOURCES] = b"".join(dev[1:])
    problems = dataset_problems(rehash(files), SPEC_MODEL)
    moved = SourceEntry.model_validate_json(dev[0])
    assert f"{TEST_SOURCES}: {moved.source_id} is marked dev" in problems


def test_an_unparseable_row_is_named_with_its_line() -> None:
    files = sealed()
    files[DEV_SOURCES] = b"{}\n" + files[DEV_SOURCES]
    problems = dataset_problems(rehash(files), SPEC_MODEL)
    assert any(p.startswith(f"{DEV_SOURCES} line 1: ") for p in problems)


def test_a_duplicated_source_is_a_problem() -> None:
    files = sealed()
    first = files[DEV_SOURCES].splitlines(keepends=True)[0]
    files[DEV_SOURCES] += first
    source = SourceEntry.model_validate_json(first).source_id
    assert f"{source} appears more than once" in dataset_problems(rehash(files), SPEC_MODEL)


def _rewrite(files: dict[str, bytes], split: CorpusSplit, edit: dict[str, object]) -> SourceEntry:
    name = sources_file(split)
    lines = files[name].splitlines(keepends=True)
    row = json.loads(lines[0])
    row.update(edit)
    lines[0] = json.dumps(row, ensure_ascii=False).encode() + b"\n"
    files[name] = b"".join(lines)
    return SourceEntry.model_validate(row)


def test_a_cluster_in_both_splits_is_a_problem() -> None:
    files = sealed()
    test_cluster = entries(files)[-1].cluster_id
    assert entries(files)[-1].split is CorpusSplit.TEST
    _rewrite(files, CorpusSplit.DEV, {"cluster_id": test_cluster})
    assert f"cluster {test_cluster} spans dev and test" in dataset_problems(rehash(files), SPEC_MODEL)


def test_a_held_out_source_in_dev_is_a_problem() -> None:
    files = sealed()
    held_out = next(q for q in SPEC_MODEL.questions if q.domain == SPEC_MODEL.held_out_domain())
    first = json.loads(files[DEV_SOURCES].splitlines()[0])
    extra = {"question_id": held_out.id, "rank": 1}
    entry = _rewrite(files, CorpusSplit.DEV, {"ranks": [*first["ranks"], extra]})
    problems = dataset_problems(rehash(files), SPEC_MODEL)
    assert f"{entry.source_id} was retrieved by a held-out question but is in dev" in problems


def test_a_rank_for_an_unknown_question_is_a_problem() -> None:
    files = sealed()
    first = json.loads(files[DEV_SOURCES].splitlines()[0])
    extra = {"question_id": "zz-unknown", "rank": 1}
    entry = _rewrite(files, CorpusSplit.DEV, {"ranks": [*first["ranks"], extra]})
    problems = dataset_problems(rehash(files), SPEC_MODEL)
    assert f"{entry.source_id} ranks unknown question zz-unknown" in problems


def test_wrong_candidate_counts_are_a_problem() -> None:
    files = sealed()
    manifest = json.loads(files[MANIFEST])
    manifest["candidate_counts"][0]["n"] += 1
    files[MANIFEST] = json.dumps(manifest).encode()
    files[SEALED] = sealed_bytes(files[MANIFEST])
    assert dataset_problems(files, SPEC_MODEL) == [f"candidate_counts in {MANIFEST} do not match the sources"]


def test_questions_must_match_the_spec() -> None:
    files = sealed()
    lines = files[QUESTIONS].splitlines(keepends=True)
    row = json.loads(lines[0])
    row["text"] += " (edited)"
    files[QUESTIONS] = json.dumps(row).encode() + b"\n" + b"".join(lines[1:])
    assert dataset_problems(rehash(files), SPEC_MODEL) == [f"{QUESTIONS}: {row['id']} differs from the spec"]


def test_a_dropped_question_is_a_problem() -> None:
    files = sealed()
    files[QUESTIONS] = b"".join(files[QUESTIONS].splitlines(keepends=True)[1:])
    expected = [f"{QUESTIONS} must hold exactly the spec's questions"]
    assert dataset_problems(rehash(files), SPEC_MODEL) == expected


# --- audits ---------------------------------------------------------------------------------------------


def _audited(spec: CorpusSpec) -> tuple[dict[str, bytes], CorpusSplit, OverstatedReason, list[str]]:
    files = sealed()
    for split in CorpusSplit:
        for kind in spec.trap_kinds:
            ids = audit_ids(entries(files), split, kind, salt=spec.audit_salt, n=spec.audit_n)
            if ids:
                return files, split, kind, list(ids)
    raise AssertionError("the fictional world has no candidates")


def _record(split: CorpusSplit, kind: OverstatedReason, ids: list[str], seal: str) -> bytes:
    decisions = tuple(AuditDecision(source_id=s, decision="confirm", reason=None) for s in ids)
    record = AuditRecord(
        split=split, kind=kind, corpus_seal=seal, prompts_sha256="a" * 64, decisions=decisions
    )
    return document_bytes(record)


def test_a_correct_audit_record_is_accepted() -> None:
    files, split, kind, ids = _audited(SPEC_MODEL)
    files[audit_file(split, kind)] = _record(split, kind, ids, sha256_hex(files[MANIFEST]))
    assert dataset_problems(files, SPEC_MODEL) == []


def test_an_audit_for_another_seal_is_a_problem() -> None:
    files, split, kind, ids = _audited(SPEC_MODEL)
    name = audit_file(split, kind)
    files[name] = _record(split, kind, ids, "b" * 64)
    assert dataset_problems(files, SPEC_MODEL) == [f"{name} was made for a different seal"]


def test_an_audit_that_skips_a_candidate_is_a_problem() -> None:
    files, split, kind, ids = _audited(SPEC_MODEL)
    name = audit_file(split, kind)
    wrong = ids[::-1] if len(ids) > 1 else ["MED:999999"]
    files[name] = _record(split, kind, wrong, sha256_hex(files[MANIFEST]))
    problems = dataset_problems(files, SPEC_MODEL)
    assert problems == [f"{name} must decide exactly the first {len(ids)} candidates in order"]


def test_an_audit_in_the_wrong_file_is_a_problem() -> None:
    files, split, kind, ids = _audited(SPEC_MODEL)
    other = next(k for k in SPEC_MODEL.trap_kinds if k is not kind)
    name = audit_file(split, other)
    files[name] = _record(split, kind, ids, sha256_hex(files[MANIFEST]))
    assert f"{name} holds the audit of {split.value}/{kind.value}" in dataset_problems(files, SPEC_MODEL)


def test_an_unparseable_audit_is_a_problem() -> None:
    files, split, kind, _ = _audited(SPEC_MODEL)
    name = audit_file(split, kind)
    files[name] = b"{}"
    problems = dataset_problems(files, SPEC_MODEL)
    assert len(problems) == 1
    assert problems[0].startswith(f"{name}: ")
