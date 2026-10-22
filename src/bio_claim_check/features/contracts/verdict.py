"""[RING:features/contracts] Claims, verifier output, verdicts and the disposition table (ADR 0006).

Why: every reported number is a count of dispositions, so the rules that produce them live in one
place, next to the models, and are total: each (label, evidence, negation) cell maps to exactly one
disposition or is impossible and raises. A Verdict keeps the LLM's judgement (`semantic_label`) and
code's evidence check (`evidence_status`) in separate fields; neither ever overwrites the other.

`Verdict.finalise` is the trusted path: evidence status and span come from `locate_quote`, never from
the LLM, and the negation result comes from a detector run on the located span, never from a stored
value. `Verdict.verify_against` re-derives all three from the abstract, so a replayed or hand-edited
verdict with a forged span or negation result is rejected. Python cannot make construction
unforgeable; a guard test keeps `Verdict(` calls inside this module.

Must not: perform I/O, call an LLM, or carry reproducibility metadata (that is the run manifest's job).
No LLM is involved in this module.
"""

from collections.abc import Callable, Mapping
from typing import Annotated, ClassVar, Self, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from bio_claim_check.common.models import NonBlankStr, ValidatedModel
from bio_claim_check.common.text import CleanedText, Span, locate_quote, near_match
from bio_claim_check.features.contracts.ids import ClaimId, SourceId
from bio_claim_check.features.contracts.labels import (
    Disposition,
    EvidenceStatus,
    FailureKind,
    Label,
    NegationCheck,
    OverstatedReason,
)


def _int_offsets(value: object) -> object:
    # pydantic coerces dataclass fields before Span.__post_init__ sees them, so `true` or `1.0`
    # in a replayed artifact would silently become an offset; reject them here
    if isinstance(value, Mapping):
        raw = cast(Mapping[str, object], value)
        if any(type(raw.get(key)) is not int for key in ("start", "end")):
            raise ValueError("span offsets must be JSON integers")
        return raw
    return value


StrictSpan = Annotated[Span, BeforeValidator(_int_offsets)]

_FROZEN = ConfigDict(frozen=True, extra="forbid")

_L, _E, _N, _D = Label, EvidenceStatus, NegationCheck, Disposition
_TABLE: Mapping[tuple[Label, EvidenceStatus, NegationCheck], Disposition] = {
    (_L.SUPPORTED, _E.LOCATED, _N.CLEAR): _D.PASSED,
    (_L.SUPPORTED, _E.LOCATED, _N.NEGATED): _D.NEEDS_REVIEW,
    (_L.SUPPORTED, _E.LOCATED, _N.NOT_RUN): _D.NEEDS_REVIEW,
    (_L.SUPPORTED, _E.NEAR, _N.NOT_RUN): _D.NEEDS_REVIEW,
    (_L.SUPPORTED, _E.ABSENT, _N.NOT_RUN): _D.FLAGGED,
    **{(label, _E.LOCATED, neg): _D.FLAGGED for label in (_L.OVERSTATED, _L.CONTRADICTED) for neg in _N},
    **{
        (label, status, _N.NOT_RUN): _D.FLAGGED
        for label in (_L.OVERSTATED, _L.CONTRADICTED)
        for status in (_E.NEAR, _E.ABSENT)
    },
    (_L.NOT_IN_SOURCE, _E.NOT_REQUIRED, _N.NOT_RUN): _D.FLAGGED,
}
"""The pre-registered disposition table. Any cell not listed here is impossible."""

_SEVERITY: tuple[Disposition, ...] = (_D.PASSED, _D.NEEDS_REVIEW, _D.FAILED, _D.FLAGGED)
"""Worst-case order for claim aggregation: a later entry outranks an earlier one."""


def disposition(label: Label, status: EvidenceStatus, negation: NegationCheck) -> Disposition:
    """Look up one cell of the disposition table; an impossible combination raises ValueError."""
    try:
        return _TABLE[(label, status, negation)]
    except KeyError:
        raise ValueError(
            f"impossible verdict: label={label.value}, evidence={status.value}, negation={negation.value}"
        ) from None


NegationDetector = Callable[[Span, CleanedText], NegationCheck]
"""Decides whether a located span sits under a negation (S10). Re-run on replay, so it must be pure."""


class Claim(ValidatedModel):
    """One atomic claim from an answer and the sources it cites, in citation order."""

    id: ClaimId
    text: NonBlankStr
    cites: tuple[SourceId, ...] = Field(min_length=1)

    @field_validator("cites", mode="before")
    @classmethod
    def _cites_are_ordered(cls, value: object) -> object:
        if not isinstance(value, list | tuple):
            raise ValueError("cites: must be an ordered list (citation order is kept)")
        return cast(object, value)

    @model_validator(mode="after")
    def _cites_are_unique(self) -> Self:
        if len(set(self.cites)) != len(self.cites):
            raise ValueError("cites: a source is cited twice")
        return self


class VerifierOutput(BaseModel):
    """What the verifier LLM may say about one (claim, source) pair.

    A flat object with every field required (nullable where noted), because strict structured-output
    modes need an object root. Per-label rules are validated after parsing; their messages name the
    field so the repair loop can quote them back to the model.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"description": "Your judgement of one claim against one cited abstract."},
    )

    label: Label
    overstated_reason: OverstatedReason | None = Field(
        description="Required when label is overstated; null otherwise."
    )
    evidence: NonBlankStr | None = Field(
        description="A verbatim quote from the abstract; null only when label is not_in_source."
    )
    reason: NonBlankStr = Field(description="One or two sentences explaining the label.")

    @model_validator(mode="after")
    def _per_label_rules(self) -> Self:
        if (self.label is Label.OVERSTATED) != (self.overstated_reason is not None):
            raise ValueError("overstated_reason: required when label is overstated, and only then")
        if (self.label is Label.NOT_IN_SOURCE) != (self.evidence is None):
            raise ValueError("evidence: required unless label is not_in_source, and must be null for it")
        return self


def _evidence(quote: str | None, abstract: CleanedText) -> tuple[EvidenceStatus, Span | None]:
    if quote is None:
        return EvidenceStatus.NOT_REQUIRED, None
    if span := locate_quote(quote, abstract):
        return EvidenceStatus.LOCATED, span
    if near_match(quote, abstract):
        return EvidenceStatus.NEAR, None
    return EvidenceStatus.ABSENT, None


def _negation(span: Span | None, abstract: CleanedText, detector: NegationDetector | None) -> NegationCheck:
    if span is None or detector is None:
        return NegationCheck.NOT_RUN
    return detector(span, abstract)


class Verdict(ValidatedModel):
    """The system's conclusion for one (claim, source) pair. Build it with `Verdict.finalise`."""

    _rebuild_hint: ClassVar[str] = "build a new one (finalise)"

    claim_id: ClaimId
    source_id: SourceId
    semantic_label: Label
    overstated_reason: OverstatedReason | None
    reason: NonBlankStr
    evidence_quote: NonBlankStr | None
    evidence_status: EvidenceStatus
    evidence_span: StrictSpan | None
    negation: NegationCheck

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        disposition(self.semantic_label, self.evidence_status, self.negation)
        if (self.semantic_label is Label.OVERSTATED) != (self.overstated_reason is not None):
            raise ValueError("overstated_reason: set if and only if semantic_label is overstated")
        if (self.evidence_status is EvidenceStatus.NOT_REQUIRED) != (self.evidence_quote is None):
            raise ValueError("evidence_quote: null if and only if evidence_status is not_required")
        if (self.evidence_status is EvidenceStatus.LOCATED) != (self.evidence_span is not None):
            raise ValueError("evidence_span: set if and only if evidence_status is located")
        return self

    @property
    def disposition(self) -> Disposition:
        return disposition(self.semantic_label, self.evidence_status, self.negation)

    @classmethod
    def finalise(
        cls,
        claim_id: ClaimId,
        source_id: SourceId,
        out: VerifierOutput,
        abstract: CleanedText,
        negation_detector: NegationDetector | None = None,
    ) -> Self:
        """Turn validated verifier output into a verdict; code, not the LLM, decides the evidence status.

        Without a detector, or when the evidence is not located, negation stays NOT_RUN (never PASSED).
        """
        status, span = _evidence(out.evidence, abstract)
        negation = _negation(span, abstract, negation_detector)
        return cls(
            claim_id=claim_id,
            source_id=source_id,
            semantic_label=out.label,
            overstated_reason=out.overstated_reason,
            reason=out.reason,
            evidence_quote=out.evidence,
            evidence_status=status,
            evidence_span=span,
            negation=negation,
        )

    def verify_against(
        self, abstract: CleanedText, negation_detector: NegationDetector | None = None
    ) -> None:
        """Raise ValueError unless the stored evidence status, span and negation re-derive from this abstract.

        A stored NOT_RUN is always accepted (it can only lower the disposition). A stored CLEAR or NEGATED
        must be reproduced by `negation_detector`; without one it cannot be checked, so it is rejected.
        """
        status, span = _evidence(self.evidence_quote, abstract)
        if (status, span) != (self.evidence_status, self.evidence_span):
            raise ValueError(
                f"verdict {self.claim_id}/{self.source_id}: stored evidence "
                f"({self.evidence_status.value}, {self.evidence_span}) does not match the abstract "
                f"({status.value}, {span})"
            )
        if self.negation is NegationCheck.NOT_RUN:
            return
        if negation_detector is None:
            raise ValueError(
                f"verdict {self.claim_id}/{self.source_id}: negation={self.negation.value} "
                "cannot be re-checked without the negation detector"
            )
        if (again := _negation(span, abstract, negation_detector)) is not self.negation:
            raise ValueError(
                f"verdict {self.claim_id}/{self.source_id}: stored negation={self.negation.value} "
                f"does not match the abstract ({again.value})"
            )


class VerifierFailure(ValidatedModel):
    """The verifier produced no usable output for one pair. Always FAILED; never silently dropped."""

    claim_id: ClaimId
    source_id: SourceId
    kind: FailureKind

    @property
    def disposition(self) -> Disposition:
        return Disposition.FAILED


class CitationNotRetrieved(ValidatedModel):
    """The claim cites a source that retrieval never returned. Always FLAGGED; never sent to a verifier."""

    claim_id: ClaimId
    source_id: SourceId

    @property
    def disposition(self) -> Disposition:
        return Disposition.FLAGGED


type PairOutcome = Verdict | VerifierFailure | CitationNotRetrieved
"""Everything that can happen to one (claim, source) pair."""


def claim_disposition(claim: Claim, outcomes: Mapping[SourceId, PairOutcome]) -> Disposition:
    """The worst disposition over every cited source (FLAGGED > FAILED > NEEDS_REVIEW > PASSED).

    Every cited source needs an explicit outcome: a missing or extra key raises, so a lost verdict can
    never shrink a denominator. An outcome filed under the wrong claim or source also raises.
    """
    if not claim.cites or len(set(claim.cites)) != len(claim.cites):
        # re-checked here because a Claim can still be forged around validation (e.g. BaseModel.model_copy)
        raise ValueError(f"claim {claim.id}: cites must be non-empty and unique, got {claim.cites}")
    if missing := set(claim.cites) - outcomes.keys():
        raise ValueError(f"claim {claim.id}: no outcome for cited sources {sorted(missing)}")
    if extra := outcomes.keys() - set(claim.cites):
        raise ValueError(f"claim {claim.id}: outcomes for uncited sources {sorted(extra)}")
    for source_id, outcome in outcomes.items():
        if (outcome.claim_id, outcome.source_id) != (claim.id, source_id):
            raise ValueError(
                f"claim {claim.id}: outcome under {source_id} belongs to "
                f"{outcome.claim_id}/{outcome.source_id}"
            )
    return max((o.disposition for o in outcomes.values()), key=_SEVERITY.index)


def verifier_output_json_schema() -> dict[str, JsonValue]:
    """The one JSON Schema every provider adapter sends verbatim (validation mode)."""
    return VerifierOutput.model_json_schema(mode="validation")
