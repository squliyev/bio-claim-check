"""Composition root: rule-pack composers, the run record's file operations and the fake wiring."""

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
    record_io,
)
from bio_claim_check.app.run_record import EVENTS_DIR, LEDGER_FILE
from bio_claim_check.app.usecases.build_corpus import CorpusFiles
from bio_claim_check.app.usecases.run import run_question
from bio_claim_check.engine.events.errors import EventWriteError
from bio_claim_check.features.contracts.corpus import CorpusSpecError
from bio_claim_check.features.contracts.labels import AnswerMode, OverstatedReason
from bio_claim_check.features.contracts.rulepack import RulePackError
from bio_claim_check.features.corpus.layout import MANIFEST
from bio_claim_check.features.report.canonical import canonical_bytes
from bio_claim_check.infrastructure.publish import PublishError
from bio_claim_check.infrastructure.text_files import read_package_bytes

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


def test_the_rule_pack_hash_is_of_the_shipped_file_bytes() -> None:
    data = read_package_bytes(*container.DEFAULT_RULEPACK)
    assert build_fake_run_ports().rules_sha256 == hashlib.sha256(data).hexdigest()


def test_record_io_publishes_once_and_refuses_different_bytes(tmp_path: Path) -> None:
    io = record_io(tmp_path)
    io.publish("abc", "report.json", b"{}\n")
    io.publish("abc", "report.json", b"{}\n")
    assert (tmp_path / "runs" / "abc" / "report.json").read_bytes() == b"{}\n"
    with pytest.raises(PublishError):
        io.publish("abc", "report.json", b"[]\n")


def test_record_io_appends_ledger_lines(tmp_path: Path) -> None:
    io = record_io(tmp_path)
    io.append_ledger(b'{"a":1}')
    io.append_ledger(b'{"a":2}')
    assert (tmp_path / LEDGER_FILE).read_bytes() == b'{"a":1}\n{"a":2}\n'


def test_record_io_opens_numbered_traces_and_fails_closed_when_all_names_are_taken(tmp_path: Path) -> None:
    io = record_io(tmp_path)
    first = io.open_trace("20260101T000000Z")
    second = io.open_trace("20260101T000000Z")
    assert (first.name, second.name) == ("20260101T000000Z-0.jsonl", "20260101T000000Z-1.jsonl")
    first.write_line(b"{}")
    first.close()
    second.close()
    assert (tmp_path / EVENTS_DIR / first.name).read_bytes() == b"{}\n"
    for n in range(2, 100):
        (tmp_path / EVENTS_DIR / f"20260101T000000Z-{n}.jsonl").touch()
    with pytest.raises(EventWriteError):
        io.open_trace("20260101T000000Z")


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
