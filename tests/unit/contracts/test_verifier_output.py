"""`VerifierOutput`: the per-label rules the repair loop relies on (ADR 0006)."""

from typing import Any, cast

import pytest
from pydantic import ValidationError

from bio_claim_check.features.contracts.verdict import VerifierOutput, verifier_output_json_schema

pytestmark = pytest.mark.unit

VALID: dict[str, dict[str, Any]] = {
    "supported": {"label": "supported", "overstated_reason": None, "evidence": "q", "reason": "r"},
    "overstated": {
        "label": "overstated",
        "overstated_reason": "preclinical_to_clinical",
        "evidence": "q",
        "reason": "r",
    },
    "contradicted": {"label": "contradicted", "overstated_reason": None, "evidence": "q", "reason": "r"},
    "not_in_source": {"label": "not_in_source", "overstated_reason": None, "evidence": None, "reason": "r"},
}


@pytest.mark.parametrize("name", VALID)
def test_valid_outputs_parse(name: str) -> None:
    assert VerifierOutput.model_validate(VALID[name]).label.value == name


@pytest.mark.parametrize(
    ("base", "change", "field"),
    [
        pytest.param(
            "overstated", {"overstated_reason": None}, "overstated_reason", id="overstated-no-reason"
        ),
        pytest.param(
            "supported", {"overstated_reason": "other"}, "overstated_reason", id="reason-not-overstated"
        ),
        pytest.param("not_in_source", {"evidence": "q"}, "evidence", id="not-in-source-with-quote"),
        pytest.param("supported", {"evidence": None}, "evidence", id="supported-no-quote"),
        pytest.param("contradicted", {"evidence": None}, "evidence", id="contradicted-no-quote"),
        pytest.param("supported", {"evidence": "  "}, "evidence", id="blank-quote"),
        pytest.param("supported", {"reason": "\n"}, "reason", id="blank-reason"),
        pytest.param("supported", {"reason": 3}, "reason", id="non-string-reason"),
        pytest.param("supported", {"label": "unsupported"}, "label", id="retired-label"),
        pytest.param("supported", {"label": "Supported"}, "label", id="label-is-case-sensitive"),
        pytest.param("supported", {"confidence": 0.9}, "confidence", id="extra-field"),
    ],
)
def test_invalid_outputs_name_the_field(base: str, change: dict[str, Any], field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        VerifierOutput.model_validate(VALID[base] | change)


@pytest.mark.parametrize("field", ["label", "overstated_reason", "evidence", "reason"])
def test_every_field_is_required_even_when_nullable(field: str) -> None:
    data = dict(VALID["supported"])
    del data[field]
    with pytest.raises(ValidationError, match=field):
        VerifierOutput.model_validate(data)


_STRICT_KEYWORDS = {
    "type", "properties", "required", "additionalProperties", "enum", "anyOf",
    "$defs", "$ref", "description", "title", "items", "pattern", "const",
}  # fmt: skip


def _strict_problems(node: object, path: str) -> list[str]:
    """Walk a schema node; names under `properties`/`$defs` are names, not keywords."""
    if isinstance(node, list):
        items = cast(list[object], node)
        return [p for i, item in enumerate(items) for p in _strict_problems(item, f"{path}[{i}]")]
    if not isinstance(node, dict):
        return []
    schema = cast(dict[str, object], node)
    problems = [
        f"{path}: keyword {k!r} not in the strict subset" for k in schema if k not in _STRICT_KEYWORDS
    ]
    if schema.get("type") == "object":
        props = cast(dict[str, object], schema.get("properties", {}))
        if schema.get("additionalProperties") is not False:
            problems.append(f"{path}: object without additionalProperties: false")
        if set(cast(list[str], schema.get("required", []))) != set(props):
            problems.append(f"{path}: not every property is required")
    for key, value in schema.items():
        if key in {"properties", "$defs"}:
            for name, sub in cast(dict[str, object], value).items():
                problems += _strict_problems(sub, f"{path}.{key}.{name}")
        elif key in {"anyOf", "items", "additionalProperties"}:
            problems += _strict_problems(value, f"{path}.{key}")
    return problems


def test_the_llm_facing_schema_is_strict_mode_compatible() -> None:
    schema = verifier_output_json_schema()
    assert schema["type"] == "object"
    assert _strict_problems(schema, "$") == []


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(
            {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}, id="open-object"
        ),
        pytest.param(
            {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False},
            id="optional",
        ),
        pytest.param({"anyOf": [{"type": "string", "minLength": 1}]}, id="nested-keyword"),
        pytest.param({"$defs": {"X": {"type": "string", "default": "x"}}}, id="default-in-defs"),
        pytest.param({"items": [{"format": "date"}]}, id="keyword-in-list"),
        pytest.param({"items": {"format": "date"}}, id="keyword-in-items"),
        pytest.param({"additionalProperties": {"format": "date"}}, id="keyword-in-additional-properties"),
    ],
)
def test_the_strict_walk_catches_what_providers_reject(bad: dict[str, object]) -> None:
    assert _strict_problems(bad, "$")


def test_property_names_are_not_mistaken_for_keywords() -> None:
    schema = {
        "type": "object",
        "properties": {"default": {"type": "string"}},
        "required": ["default"],
        "additionalProperties": False,
    }
    assert _strict_problems(schema, "$") == []
