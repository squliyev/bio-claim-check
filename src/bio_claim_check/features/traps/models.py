"""[RING:features/traps] The trap set's records: what the writer drafts, what the author confirms.

Why: a trap is only useful with ground truth, a clean parent to pair it with, and an honest origin. A
`DraftRow` is everything generation produced, including writer failures and gate exclusions, and stays in
`var/`. A `TrapItem` is a row the author confirmed; only those are committed (ADR 0022). The origin
records who drafted the text (`model` plus the deployment) and, separately, who confirmed it, so an AI
draft is never relabelled human. A trap points to its parent through `pair_id` instead of copying it.
Must not: hold abstract text (ADR 0008), or let a trap's metadata reach the verifier (ids are opaque).

No LLM is involved in this module.
"""

import hashlib
from dataclasses import dataclass
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bio_claim_check.common.models import NonBlankStr, Sha256Hex, ValidatedModel
from bio_claim_check.common.text import CleanedText
from bio_claim_check.features.contracts.ids import ClaimId, SourceId
from bio_claim_check.features.contracts.labels import Disposition, FailureKind, Label, OverstatedReason

MAX_CLAIM_WORDS: Final = 30
"""A trap or parent is a short statement about an abstract, never a copied sentence of it (ADR 0008)."""

TRAP_SALT: Final = "bio-claim-check/traps/v1"
"""Public salt for the sampling order and the opaque ids (ADR 0022)."""

Role = Literal["parent", "trap"]
Generator = Literal["model", "rule_floor"]
FloorRule = Literal["direction", "operator", "dose"]
Origin = Literal["author", "external_expert", "model"]


def opaque_id(source_id: SourceId, role: Role, rule: FloorRule | None) -> ClaimId:
    """`t` + 11 hex characters: stable for a (source, role, rule), and says nothing about any of them."""
    digest = hashlib.sha256(f"{TRAP_SALT}|{source_id}|{role}|{rule or '-'}".encode()).hexdigest()
    return "t" + digest[:11]


@dataclass(frozen=True, slots=True)
class TrapPayload:
    """What the trap writer sees: one kind's definition and one paper. No id, question or other paper."""

    reason: str
    definition: str
    title: str
    abstract: CleanedText


class TrapDraft(BaseModel):
    """What the trap writer returns for one source: flat, every field required (strict structured output)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "description": "One supported claim about the abstract and its overstated rewrite."
        },
    )

    parent: NonBlankStr = Field(
        description="A claim the abstract fully supports, in your own words, at most 30 words."
    )
    trap: NonBlankStr = Field(
        description="The same claim rewritten to commit exactly the asked overstatement, at most 30 words."
    )


class TrapWriterFailure(ValidatedModel):
    """The writer produced no usable draft for one source. Counted in the draft file, never dropped."""

    source_id: SourceId
    kind: FailureKind


class DraftRow(ValidatedModel):
    """One generated row: a candidate for the audit (no problems, no failure) or a logged exclusion."""

    id: ClaimId
    pair_id: ClaimId
    role: Role
    kind: OverstatedReason
    question_id: NonBlankStr
    source_id: SourceId
    abstract_sha256: Sha256Hex
    claim: NonBlankStr | None
    generator: Generator
    rule: FloorRule | None
    origin_id: NonBlankStr
    problems: tuple[NonBlankStr, ...] = ()
    failure: FailureKind | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.claim is None) != (self.failure is not None):
            raise ValueError("claim: missing if and only if the writer failed")
        if (self.generator == "rule_floor") != (self.rule is not None):
            raise ValueError("rule: set if and only if the row is a rule-floor trap")
        if self.role == "parent" and (self.generator != "model" or self.pair_id != self.id):
            raise ValueError("a parent is drafted by the model and is its own pair")
        return self

    @property
    def candidate(self) -> bool:
        """Goes to the audit sheet: drafted, and passed the validity gate."""
        return self.failure is None and not self.problems


class TrapItem(ValidatedModel):
    """One author-confirmed row of the committed trap set (I76)."""

    id: ClaimId
    pair_id: ClaimId
    role: Role
    kind: OverstatedReason
    question_id: NonBlankStr
    source_id: SourceId
    abstract_sha256: Sha256Hex
    claim: NonBlankStr
    expected_disposition: Disposition
    expected_label: Label | None
    expected_reason: OverstatedReason | None
    generator: Generator
    rule: FloorRule | None
    origin: Origin
    origin_id: NonBlankStr
    confirmed_by: Literal["author"]

    @model_validator(mode="after")
    def _ground_truth(self) -> Self:
        if len(self.claim.split()) > MAX_CLAIM_WORDS or self.claim != self.claim.strip():
            raise ValueError(f"claim: at most {MAX_CLAIM_WORDS} words, no surrounding whitespace")
        if self.id != opaque_id(self.source_id, self.role, self.rule):
            raise ValueError("id: not the opaque id of this source, role and rule")
        if (self.generator == "rule_floor") != (self.rule is not None):
            raise ValueError("rule: set if and only if the row is a rule-floor trap")
        truth = (self.expected_disposition, self.expected_label, self.expected_reason)
        if truth != expected_truth(self.role, self.generator, self.kind):
            raise ValueError("expected_*: not the ground truth for this role and generator (ADR 0022)")
        if self.role == "parent" and (self.generator != "model" or self.pair_id != self.id):
            raise ValueError("a parent is drafted by the model and is its own pair")
        return self


def expected_truth(
    role: Role, generator: Generator, kind: OverstatedReason
) -> tuple[Disposition, Label | None, OverstatedReason | None]:
    """The predeclared ground truth (ADR 0022): a parent passes; a model trap is overstated for its kind; a
    rule-floor trap is flagged with either label (contradicted or not in source)."""
    if role == "parent":
        return Disposition.PASSED, Label.SUPPORTED, None
    if generator == "model":
        return Disposition.FLAGGED, Label.OVERSTATED, kind
    return Disposition.FLAGGED, None, None
