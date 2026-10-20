"""`RulePack` models: coverage of every reason, example/rule consistency, strict versions."""

import copy
from typing import Any, cast

import pytest
from pydantic import ValidationError

from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.contracts.rulepack import (
    RulePack,
    RulePackError,
    parse_rulepack,
    rulepack_json_schema,
)

pytestmark = pytest.mark.unit

REASONS = [r for r in OverstatedReason if r is not OverstatedReason.OTHER]


def _pack() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "version": "0.1.0",
        "authors": ["A. Author"],
        "rules": [
            {
                "id": reason.value,
                "reason": reason.value,
                "definition": "d",
                "cues": ["c"],
                "examples": [
                    {
                        "claim": "x",
                        "source_excerpt": "y",
                        "label": "overstated",
                        "overstated_reason": reason.value,
                        "note": "n",
                    },
                    {
                        "claim": "x",
                        "source_excerpt": "y",
                        "label": "supported",
                        "overstated_reason": None,
                        "note": "n",
                        "reviewed_by": ["Dr Expert"],
                    },
                ],
                "references": [],
            }
            for reason in REASONS
        ],
    }


def test_a_complete_pack_validates_and_is_frozen() -> None:
    pack = RulePack.model_validate(_pack())
    assert {r.reason for r in pack.rules} == set(REASONS)
    assert pack.rules[0].examples[0].reviewed_by == ()
    with pytest.raises(ValidationError, match="frozen"):
        pack.version = "9.9.9"


def _set(data: dict[str, Any], path: str, value: object) -> dict[str, Any]:
    data = copy.deepcopy(data)
    *parents, last = path.split(".")
    node: Any = data
    for part in parents:
        node = node[int(part)] if part.isdigit() else node[part]
    if value is _DELETE:
        del node[int(last) if last.isdigit() else last]
    elif last.isdigit():
        node[int(last)] = value
    else:
        node[last] = value
    return data


_DELETE = object()


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        pytest.param("schema_version", True, "integer 1", id="schema-version-bool"),
        pytest.param("schema_version", 1.0, "integer 1", id="schema-version-float"),
        pytest.param("schema_version", 2, "schema_version", id="schema-version-2"),
        pytest.param("version", 1.0, "version", id="version-float"),
        pytest.param("version", "1.0", "version", id="version-not-semver"),
        pytest.param("authors", [], "authors", id="no-authors"),
        pytest.param("authors.0", "  ", "authors", id="blank-author"),
        pytest.param("rules", [], "no rule for reasons", id="no-rules"),
        pytest.param("rules.0.id", "rules.1.id", "rules.0.id", id="bad-id-pattern"),
        pytest.param("rules.0.id", "surrogate_as_clinical", "duplicate ids", id="duplicate-id"),
        pytest.param("rules.0.reason", "other", "verifier fallback", id="other-as-rule"),
        pytest.param("rules.0.cues", [], "cues", id="no-cues"),
        pytest.param("rules.0.definition", "", "definition", id="blank-definition"),
        pytest.param(
            "rules.0.examples.0.overstated_reason", None, "overstated_reason", id="overstated-no-reason"
        ),
        pytest.param(
            "rules.0.examples.0.overstated_reason",
            "certainty_inflation",
            "overstated_reason",
            id="wrong-reason",
        ),
        pytest.param(
            "rules.0.examples.1.overstated_reason",
            "certainty_inflation",
            "overstated_reason",
            id="supported-with-reason",
        ),
        pytest.param("rules.0.examples.0.label", "contradicted", "label", id="contradicted-example"),
        pytest.param("rules.0.examples.0.label", "Overstated", "label", id="label-case"),
        pytest.param("rules.0.examples.0.claim", False, "claim", id="norway-bool"),
        pytest.param("rules.0.examples.0.extra", "x", "extra", id="unknown-key"),
        pytest.param("rules.0.examples.0.note", _DELETE, "note", id="missing-note"),
        pytest.param(
            "rules.0.examples.0.reviewed_by", ["Dr A", "Dr A"], "reviewer twice", id="duplicate-reviewer"
        ),
    ],
)
def test_invalid_packs_are_rejected(path: str, value: object, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        RulePack.model_validate(_set(_pack(), path, value))


def test_a_missing_reason_is_named() -> None:
    data = _pack()
    data["rules"] = [r for r in data["rules"] if r["reason"] != "certainty_inflation"]
    with pytest.raises(ValidationError, match="certainty_inflation"):
        RulePack.model_validate(data)


def test_the_rulepack_schema_describes_the_yaml_shape() -> None:
    schema = rulepack_json_schema()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(cast(dict[str, object], schema["properties"])) == {
        "schema_version",
        "version",
        "authors",
        "rules",
    }


@pytest.mark.parametrize(
    ("data", "problems"),
    [
        pytest.param(None, ["pack.yaml: the file is empty"], id="empty"),
        pytest.param(
            [1],
            ["pack.yaml: (root): Input should be a valid dictionary or instance of RulePack"],
            id="root-list",
        ),
        pytest.param(
            {"schema_version": 1},
            [
                "pack.yaml: version: Field required",
                "pack.yaml: authors: Field required",
                "pack.yaml: rules: Field required",
            ],
            id="field-paths",
        ),
    ],
)
def test_parse_rulepack_reports_one_located_line_per_problem(data: object, problems: list[str]) -> None:
    with pytest.raises(RulePackError) as info:
        parse_rulepack(data, "pack.yaml")
    assert info.value.problems == tuple(problems)
    assert str(info.value) == "\n".join(problems)


def test_parse_rulepack_accepts_a_valid_pack() -> None:
    assert parse_rulepack(_pack(), "pack.yaml") == RulePack.model_validate(_pack())
