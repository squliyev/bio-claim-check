"""Composition root: rule-pack composers, report publishing and the fake wiring (S05b)."""

import hashlib
import json
from pathlib import Path

import pytest
from tests.support.corpus import SPEC_FILE

from bio_claim_check.app import container
from bio_claim_check.app.container import (
    OutputConflictError,
    build_fake_run_ports,
    default_rulepack,
    load_corpus_spec,
    load_rulepack,
    publish_corpus,
    publish_report,
)
from bio_claim_check.app.usecases.build_corpus import CorpusFiles
from bio_claim_check.app.usecases.run import run_question
from bio_claim_check.features.contracts.corpus import CorpusSpecError
from bio_claim_check.features.contracts.labels import AnswerMode, OverstatedReason
from bio_claim_check.features.contracts.rulepack import RulePackError
from bio_claim_check.features.corpus.layout import MANIFEST
from bio_claim_check.features.report.canonical import canonical_bytes, run_id

pytestmark = pytest.mark.unit

REPORT = run_question(build_fake_run_ports(), "Does OS-912 work?", AnswerMode.STRICT, k=4)


def test_the_shipped_pack_covers_every_reason_and_is_author_written() -> None:
    pack = default_rulepack()
    assert {r.reason for r in pack.rules} == set(OverstatedReason) - {OverstatedReason.OTHER}
    examples = [e for r in pack.rules for e in r.examples]
    assert examples
    assert all(e.reviewed_by == () for e in examples), "no example may claim review it did not get"
    assert all({e.label.value for e in r.examples} == {"supported", "overstated"} for r in pack.rules)


def test_a_missing_file_is_a_rulepack_error(tmp_path: Path) -> None:
    with pytest.raises(RulePackError, match="cannot read"):
        load_rulepack(tmp_path / "missing.yaml")


def test_unreadable_default_pack_is_a_rulepack_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container, "DEFAULT_RULEPACK", ("data", "rulepacks", "missing.yaml"))
    with pytest.raises(RulePackError, match=r"^package data data/rulepacks/missing\.yaml: cannot read: "):
        container.default_rulepack()


def test_yaml_problems_become_rulepack_errors(tmp_path: Path) -> None:
    path = tmp_path / "pack.yaml"
    path.write_text("a: 1\na: 2\n", encoding="utf-8")
    with pytest.raises(RulePackError, match=f"{path}:2: duplicate key"):
        load_rulepack(path)


def test_canonical_bytes_are_sorted_utf8_with_a_trailing_newline() -> None:
    data = canonical_bytes(REPORT)
    assert data.endswith(b"}\n")
    assert (
        data == (json.dumps(json.loads(data), sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
    )
    assert "run_id" not in data.decode()


def test_publish_report_names_the_folder_by_content_hash(tmp_path: Path) -> None:
    path = publish_report(tmp_path, REPORT)
    data = canonical_bytes(REPORT)
    assert run_id(data) == hashlib.sha256(data).hexdigest()[:16]
    assert path == tmp_path / run_id(data) / "report.json"
    assert path.read_bytes() == data


def test_load_corpus_spec_reads_the_fixture() -> None:
    spec = load_corpus_spec(SPEC_FILE)
    assert spec.held_out_domain() == "statin-neuro"


def test_a_missing_corpus_spec_is_one_problem(tmp_path: Path) -> None:
    with pytest.raises(CorpusSpecError) as caught:
        load_corpus_spec(tmp_path / "missing.yaml")
    assert len(caught.value.problems) == 1
    assert "missing.yaml" in caught.value.problems[0]


def test_corpus_spec_yaml_problems_name_the_file_and_line(tmp_path: Path) -> None:
    path = tmp_path / "spec.yaml"
    path.write_text("a: 1\na: 2\n", encoding="utf-8")
    with pytest.raises(CorpusSpecError) as caught:
        load_corpus_spec(path)
    assert caught.value.problems == (f"{path}:2: duplicate key 'a'",)


def test_publish_corpus_writes_data_files_then_the_manifest(tmp_path: Path) -> None:
    files = CorpusFiles(data={"b/x.jsonl": b"x\n", "a.jsonl": b"a\n"}, manifest=b"{}\n")
    paths = publish_corpus(tmp_path, files)
    assert paths == [tmp_path / "a.jsonl", tmp_path / "b" / "x.jsonl", tmp_path / MANIFEST]
    assert (tmp_path / "b" / "x.jsonl").read_bytes() == b"x\n"
    assert publish_corpus(tmp_path, files) == paths


def test_publish_corpus_refuses_a_different_file_and_skips_the_manifest(tmp_path: Path) -> None:
    (tmp_path / "a.jsonl").write_bytes(b"old\n")
    files = CorpusFiles(data={"a.jsonl": b"a\n", "b.jsonl": b"b\n"}, manifest=b"{}\n")
    with pytest.raises(OutputConflictError):
        publish_corpus(tmp_path, files)
    assert (tmp_path / "a.jsonl").read_bytes() == b"old\n"
    assert not (tmp_path / MANIFEST).exists()


def test_publish_corpus_checks_the_old_manifest_before_writing_any_data(tmp_path: Path) -> None:
    (tmp_path / MANIFEST).write_bytes(b"old manifest\n")
    files = CorpusFiles(data={"a.jsonl": b"a\n"}, manifest=b"{}\n")
    with pytest.raises(OutputConflictError):
        publish_corpus(tmp_path, files)
    assert not (tmp_path / "a.jsonl").exists()


@pytest.mark.parametrize("kind", ["directory_destination", "out_is_a_file"])
def test_publish_corpus_maps_filesystem_errors_to_a_conflict(tmp_path: Path, kind: str) -> None:
    out = tmp_path / "out"
    if kind == "directory_destination":
        (out / "a.jsonl").mkdir(parents=True)
    else:
        out.write_bytes(b"not a folder\n")
    with pytest.raises(OutputConflictError):
        publish_corpus(out, CorpusFiles(data={"a.jsonl": b"a\n"}, manifest=b"{}\n"))
