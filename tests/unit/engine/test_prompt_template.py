"""Prompt templates: hash from text, strict rendering in both directions, no re-substitution."""

import pytest
from pydantic import ValidationError

from bio_claim_check.engine.prompts.prompt_template import PromptRenderError, PromptTemplate, render

pytestmark = pytest.mark.unit

TEMPLATE = PromptTemplate(
    name="verify",
    version=1,
    system="Judge only from the abstract. Cost: $$0.",
    user="Claim: $claim\n${abstract}",
)


def test_render_fills_system_and_user() -> None:
    system, user = render(TEMPLATE, {"claim": "X lowers Y", "abstract": "We found X lowers Y."})
    assert (system.role, system.content) == ("system", "Judge only from the abstract. Cost: $0.")
    assert (user.role, user.content) == ("user", "Claim: X lowers Y\nWe found X lowers Y.")


def test_a_dollar_name_inside_a_value_is_not_expanded_again() -> None:
    _, user = render(TEMPLATE, {"claim": "$abstract", "abstract": "costs $5 (${claim})"})
    assert user.content == "Claim: $abstract\ncosts $5 (${claim})"


@pytest.mark.parametrize(
    ("variables", "message"),
    [
        ({"claim": "c"}, "missing ['abstract'], extra []"),
        ({"claim": "c", "abstract": "a", "rules": "r"}, "missing [], extra ['rules']"),
        ({"rules": "r"}, "missing ['abstract', 'claim'], extra ['rules']"),
    ],
)
def test_variables_must_equal_placeholders(variables: dict[str, str], message: str) -> None:
    with pytest.raises(
        PromptRenderError, match=r"verify v1: " + message.replace("[", r"\[").replace("]", r"\]")
    ):
        render(TEMPLATE, variables)


def test_placeholders_span_both_parts() -> None:
    t = PromptTemplate(name="n", version=1, system="Rules: $rules", user="$claim and $claim")
    assert t.placeholders == {"rules", "claim"}


@pytest.mark.parametrize("bad", ["costs $5", "trailing $", "${unclosed"])
def test_invalid_placeholder_is_rejected_at_construction(bad: str) -> None:
    with pytest.raises(ValidationError, match="invalid placeholder"):
        PromptTemplate(name="n", version=1, system="ok", user=bad)


@pytest.mark.parametrize(
    "fields", [{"name": " "}, {"version": 0}, {"version": True}, {"system": ""}, {"user": "\n"}]
)
def test_fields_are_validated(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PromptTemplate.model_validate({**TEMPLATE.model_dump(), **fields})


@pytest.mark.parametrize(
    "change",
    [{"name": "verify2"}, {"version": 2}, {"system": "Other."}, {"user": "Claim: $claim\n$abstract "}],
)
def test_any_change_changes_the_hash(change: dict[str, object]) -> None:
    other = PromptTemplate.model_validate({**TEMPLATE.model_dump(), **change})
    assert other.sha256 != TEMPLATE.sha256


def test_hash_is_stable_and_ref_carries_it() -> None:
    again = PromptTemplate.model_validate(TEMPLATE.model_dump())
    assert again.sha256 == TEMPLATE.sha256
    assert len(TEMPLATE.sha256) == 64
    ref = TEMPLATE.ref()
    assert (ref.name, ref.version, ref.sha256) == ("verify", 1, TEMPLATE.sha256)
