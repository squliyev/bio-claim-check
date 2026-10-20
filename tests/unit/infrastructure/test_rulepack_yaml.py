"""YAML loading: every ambiguous construct is refused with a location; the shipped pack is valid."""

from pathlib import Path

import pytest

from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.infrastructure.rulepack_yaml import (
    RulePackError,
    load_default_rulepack,
    load_rulepack,
    parse_rulepack,
)

pytestmark = pytest.mark.unit


def test_the_shipped_pack_covers_every_reason_and_is_author_written() -> None:
    pack = load_default_rulepack()
    assert {r.reason for r in pack.rules} == set(OverstatedReason) - {OverstatedReason.OTHER}
    examples = [e for r in pack.rules for e in r.examples]
    assert examples
    assert all(e.reviewed_by == () for e in examples), "no example may claim review it did not get"
    assert all({e.label.value for e in r.examples} == {"supported", "overstated"} for r in pack.rules)


def _problems(text: str) -> str:
    with pytest.raises(RulePackError) as info:
        parse_rulepack(text, "pack.yaml")
    return "\n".join(info.value.problems)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("a: 1\na: 2\n", "pack.yaml:2: duplicate key 'a'", id="duplicate-root"),
        pytest.param("a:\n  b: 1\n  b: 2\n", "pack.yaml:3: duplicate key 'b'", id="duplicate-nested"),
        pytest.param("- a: 1\n  a: 1\n", "pack.yaml:2: duplicate key 'a'", id="duplicate-in-list"),
        pytest.param("a: &x 1\nb: *x\n", "pack.yaml:1: anchors and aliases", id="anchor-alias"),
        pytest.param("a: &x 1\n", "pack.yaml:1: anchors", id="unused-anchor"),
        pytest.param("base: {a: 1}\nm:\n  <<: {a: 1}\n", "pack.yaml:3: merge keys", id="merge"),
        pytest.param("1: x\n", "keys must be plain strings", id="int-key"),
        pytest.param("no: x\n", "keys must be plain strings", id="norway-key"),
        pytest.param("a: !!binary aGVsbG8=\n", "a: bytes values are not allowed", id="binary"),
        pytest.param("a:\n  - 2024-01-01\n", "a.0: date values are not allowed", id="timestamp"),
        pytest.param("a: !!set {x}\n", "a: set values are not allowed", id="set"),
        pytest.param("a: !!python/object:os.system x\n", "pack.yaml:1:", id="python-tag"),
        pytest.param("a: [1\n", "pack.yaml:", id="syntax-error"),
        pytest.param("", "the file is empty", id="empty"),
        pytest.param("# only a comment\n", "the file is empty", id="comment-only"),
        pytest.param("- 1\n", "(root): Input should be a valid dictionary", id="root-list"),
        pytest.param("schema_version: 1\n", "pack.yaml: version: Field required", id="model-error-has-path"),
        pytest.param("a: !!str\n  - 1\n", "pack.yaml:", id="bad-tag-on-sequence"),
        pytest.param("a: " + "[" * 2000 + "]" * 2000, "pack.yaml: nesting is too deep", id="deep-nesting"),
    ],
)
def test_ambiguous_yaml_is_refused_with_a_location(text: str, expected: str) -> None:
    assert expected in _problems(text)


def test_a_missing_file_is_a_rulepack_error(tmp_path: Path) -> None:
    with pytest.raises(RulePackError, match="cannot read"):
        load_rulepack(tmp_path / "missing.yaml")


def test_load_rulepack_reads_a_file(tmp_path: Path) -> None:
    path = tmp_path / "pack.yaml"
    path.write_text("a: 1\na: 2\n", encoding="utf-8")
    with pytest.raises(RulePackError, match=f"{path}:2: duplicate key"):
        load_rulepack(path)
