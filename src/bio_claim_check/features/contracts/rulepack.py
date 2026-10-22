"""[RING:features/contracts] The rule pack: domain knowledge the verifier is given, as data.

Why: the ways papers get overstated are a researcher's knowledge, not code. A pack is a versioned,
authored document that researchers can extend by pull request without writing Python. Every example
records who reviewed it; an empty `reviewed_by` means author-written and is never reported as
expert-labelled. Models are frozen: the verifier never edits its own rules (they change only by PR).
`parse_rulepack` turns already-parsed data into a pack with one located problem per line; reading and
YAML parsing live in infrastructure, and the app composes them (S05b).
Must not: read files or parse YAML, or encode one lab's rules as defaults in code.

No LLM is involved in this module.
"""

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    model_validator,
)

from bio_claim_check.common.errors import BccError
from bio_claim_check.common.models import NonBlankStr
from bio_claim_check.features.contracts.labels import Label, OverstatedReason

_FROZEN = ConfigDict(frozen=True, extra="forbid")


def _exact_int(value: object) -> object:
    # Literal[1] alone would accept `true` and `1.0` from YAML
    if type(value) is not int:
        raise ValueError("must be the integer 1")
    return value


class RuleExample(BaseModel):
    """A claim next to the source excerpt it was built from. Entities are fictional by convention."""

    model_config = _FROZEN

    claim: NonBlankStr
    source_excerpt: NonBlankStr
    label: Literal[Label.SUPPORTED, Label.OVERSTATED]
    overstated_reason: OverstatedReason | None
    note: NonBlankStr
    reviewed_by: tuple[NonBlankStr, ...] = ()

    @model_validator(mode="after")
    def _reviewers_are_unique(self) -> Self:
        if len(set(self.reviewed_by)) != len(self.reviewed_by):
            raise ValueError("reviewed_by lists a reviewer twice")
        return self


class Rule(BaseModel):
    """One way a claim can go beyond its source, with cues and contrasting examples."""

    model_config = _FROZEN

    id: Annotated[str, Field(strict=True, pattern=r"^[a-z][a-z0-9_]*$")]
    reason: OverstatedReason
    definition: NonBlankStr
    cues: tuple[NonBlankStr, ...] = Field(min_length=1)
    examples: tuple[RuleExample, ...]
    references: tuple[NonBlankStr, ...]

    @model_validator(mode="after")
    def _examples_match_the_rule(self) -> Self:
        if self.reason is OverstatedReason.OTHER:
            raise ValueError("reason: 'other' is a verifier fallback, not a rule")
        for i, example in enumerate(self.examples):
            expected = self.reason if example.label is Label.OVERSTATED else None
            if example.overstated_reason is not expected:
                raise ValueError(
                    f"examples.{i}.overstated_reason: must be {expected and expected.value} "
                    f"for a {example.label.value} example of rule {self.id}"
                )
        return self


class RulePack(BaseModel):
    """A versioned, authored set of rules covering every overstatement reason except `other`."""

    model_config = _FROZEN

    schema_version: Annotated[Literal[1], BeforeValidator(_exact_int)]
    version: Annotated[str, Field(strict=True, pattern=r"^\d+\.\d+\.\d+$")]
    authors: tuple[NonBlankStr, ...] = Field(min_length=1)
    rules: tuple[Rule, ...]

    @model_validator(mode="after")
    def _ids_unique_and_reasons_covered(self) -> Self:
        ids = [rule.id for rule in self.rules]
        if duplicates := sorted({i for i in ids if ids.count(i) > 1}):
            raise ValueError(f"rules: duplicate ids {duplicates}")
        missing = set(OverstatedReason) - {OverstatedReason.OTHER} - {rule.reason for rule in self.rules}
        if missing:
            raise ValueError(f"rules: no rule for reasons {sorted(m.value for m in missing)}")
        return self


def rulepack_json_schema() -> dict[str, JsonValue]:
    """JSON Schema for editors and reviewers of rule-pack YAML (validation mode)."""
    return RulePack.model_json_schema(mode="validation")


class RulePackError(BccError):
    """A rule pack could not be loaded. `problems` holds one human-readable line per problem."""

    code = "contracts.rule_pack"

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = tuple(problems)


def parse_rulepack(data: object, source: str) -> RulePack:
    """Validate parsed data (None = an empty file) as a rule pack; `source` names it in every problem."""
    if data is None:
        raise RulePackError([f"{source}: the file is empty"])
    try:
        return RulePack.model_validate(data)
    except ValidationError as err:
        problems: list[str] = []
        for problem in err.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in problem["loc"]) or "(root)"
            problems.append(f"{source}: {location}: {problem['msg']}")
        raise RulePackError(problems) from None
