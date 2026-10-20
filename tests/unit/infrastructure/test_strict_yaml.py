"""Strict YAML: every ambiguous construct is refused with a location; plain data passes through."""

import pytest

from bio_claim_check.infrastructure.strict_yaml import StrictYamlError, load_strict_yaml

pytestmark = pytest.mark.unit


def _problems(text: str) -> str:
    with pytest.raises(StrictYamlError) as info:
        load_strict_yaml(text, "pack.yaml")
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
        pytest.param("!!binary aGVsbG8=\n", "pack.yaml: (root): bytes values", id="root-binary"),
        pytest.param("a: !!python/object:os.system x\n", "pack.yaml:1:", id="python-tag"),
        pytest.param("a: [1\n", "pack.yaml:", id="syntax-error"),
        pytest.param("a: !!str\n  - 1\n", "pack.yaml:", id="bad-tag-on-sequence"),
        pytest.param("a: " + "[" * 2000 + "]" * 2000, "pack.yaml: nesting is too deep", id="deep-nesting"),
    ],
)
def test_ambiguous_yaml_is_refused_with_a_location(text: str, expected: str) -> None:
    assert expected in _problems(text)


@pytest.mark.parametrize(
    ("text", "data"),
    [
        pytest.param("", None, id="empty"),
        pytest.param("# only a comment\n", None, id="comment-only"),
        pytest.param("- 1\n- x\n", [1, "x"], id="root-list"),
        pytest.param(
            "a: {b: [1, 2.5, true, null, 'no']}\n", {"a": {"b": [1, 2.5, True, None, "no"]}}, id="nested"
        ),
    ],
)
def test_plain_data_passes_through_unchanged(text: str, data: object) -> None:
    assert load_strict_yaml(text, "pack.yaml") == data
