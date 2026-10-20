"""Composition root: rule-pack composers, report publishing and the fake wiring (S05b)."""

import hashlib
import json
from pathlib import Path

import pytest

from bio_claim_check.app import container
from bio_claim_check.app.container import (
    build_fake_run_ports,
    default_rulepack,
    load_rulepack,
    publish_report,
)
from bio_claim_check.app.usecases.run import run_question
from bio_claim_check.features.contracts.labels import AnswerMode, OverstatedReason
from bio_claim_check.features.contracts.rulepack import RulePackError
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
