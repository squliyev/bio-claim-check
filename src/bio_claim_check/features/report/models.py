"""[RING:features/report] The report: what was asked, what was retrieved, and what happened to each pair.

Why: the report is the artifact a reader trusts, so it stores only inputs (papers, claims, outcomes,
findings) and derives every disposition and count. Derived values appear in the JSON, but on load they
must equal what the model recomputes, so a stored number can never be forged or stale (invariant I20).
Integrity is checked on construction, not only by the use case: every verdict is re-located against its
paper's cleaned abstract, every invented-citation finding matches a not-retrieved pair, every finding
names a claim in the report, and a fake report may only cite `FAKE:` sources (I19). A live report names
its answerer and verifier and flags when they share a family (I71).
Must not: change or re-judge an outcome, or compute rates (counts only; denominators are explicit).

No LLM is involved in this module.
"""

from collections import Counter
from typing import Annotated, Any, Final, Literal, Self, cast

from pydantic import Field, ModelWrapValidatorHandler, computed_field, model_validator
from pydantic_core import to_jsonable_python

from bio_claim_check.common.model_family import ModelFamily
from bio_claim_check.common.models import NonBlankStr, ValidatedModel
from bio_claim_check.features.contracts.finding import Finding, FindingKind
from bio_claim_check.features.contracts.labels import AnswerMode, Disposition
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.verdict import (
    CitationNotRetrieved,
    Claim,
    PairOutcome,
    Verdict,
    VerifierFailure,
    claim_disposition,
)

FAKE_NOTICE: Final = "FAKE RUN: fictional papers, scripted answer and verdicts. Not a result."
LIVE_NOTICE: Final = (
    "LLM answer; each claim, if any, checked by an LLM verifier against the retrieved abstracts it cites. "
    "Labels are model judgements, not expert review."
)
FAKE_PREFIX: Final = "FAKE:"

type Provenance = Literal["fake", "live"]


class _Derived(ValidatedModel):
    """Derived (computed) fields may be present on input only if they equal the recomputed value."""

    @model_validator(mode="wrap")
    @classmethod
    def _derived_values_match(cls, data: Any, handler: ModelWrapValidatorHandler[Self]) -> Self:
        stored: dict[str, object] = {}
        if isinstance(data, dict):
            data = dict(cast("dict[str, object]", data))
            stored = {name: data.pop(name) for name in cls.model_computed_fields if name in data}
        model = handler(data)
        for name, value in stored.items():
            if to_jsonable_python(value) != to_jsonable_python(getattr(model, name)):
                raise ValueError(f"{name}: stored value does not match the value derived from the inputs")
        return model


def _counts(dispositions: list[Disposition]) -> dict[Disposition, int]:
    counter = Counter(dispositions)
    return {d: counter[d] for d in Disposition}


class VerdictPair(_Derived):
    outcome: Literal["verdict"] = "verdict"
    verdict: Verdict

    @property
    def result(self) -> PairOutcome:
        return self.verdict

    @computed_field
    @property
    def disposition(self) -> Disposition:
        return self.verdict.disposition


class FailurePair(_Derived):
    outcome: Literal["failure"] = "failure"
    failure: VerifierFailure

    @property
    def result(self) -> PairOutcome:
        return self.failure

    @computed_field
    @property
    def disposition(self) -> Disposition:
        return self.failure.disposition


class NotRetrievedPair(_Derived):
    outcome: Literal["citation_not_retrieved"] = "citation_not_retrieved"
    citation: CitationNotRetrieved

    @property
    def result(self) -> PairOutcome:
        return self.citation

    @computed_field
    @property
    def disposition(self) -> Disposition:
        return self.citation.disposition


PairReport = Annotated[VerdictPair | FailurePair | NotRetrievedPair, Field(discriminator="outcome")]
"""One (claim, source) pair and its outcome, tagged so the outcome type survives a JSON round trip."""


def pair_report(outcome: PairOutcome) -> VerdictPair | FailurePair | NotRetrievedPair:
    """Wrap an outcome in its tagged report entry."""
    if isinstance(outcome, Verdict):
        return VerdictPair(verdict=outcome)
    if isinstance(outcome, VerifierFailure):
        return FailurePair(failure=outcome)
    return NotRetrievedPair(citation=outcome)


class ClaimReport(_Derived):
    """One claim and one outcome per cited source, in citation order."""

    claim: Claim
    pairs: tuple[PairReport, ...]

    @model_validator(mode="after")
    def _pairs_follow_cites(self) -> Self:
        if tuple(p.result.source_id for p in self.pairs) != self.claim.cites:
            raise ValueError(f"claim {self.claim.id}: pairs must follow the cited sources in order")
        claim_disposition(
            self.claim, {p.result.source_id: p.result for p in self.pairs}
        )  # raises on mismatch
        return self

    @computed_field
    @property
    def disposition(self) -> Disposition:
        """Worst case over the cited sources (ADR 0006)."""
        return claim_disposition(self.claim, {p.result.source_id: p.result for p in self.pairs})


class ModelUse(ValidatedModel):
    """Which deployment played a role, and who trained it."""

    deployment: NonBlankStr
    family: ModelFamily


class RunModels(_Derived):
    """The answerer and the verifier of a live run. Same-family use is allowed but flagged (ADR 0019)."""

    answerer: ModelUse
    verifier: ModelUse

    @computed_field
    @property
    def same_family(self) -> bool:
        """True when one model family both answered and judged: its blind spots may agree."""
        return self.answerer.family == self.verifier.family


class Report(_Derived):
    """The full record of one run. Counts are over pairs and over claims; FAILED stays in both."""

    provenance: Provenance
    question: NonBlankStr
    mode: AnswerMode
    papers: tuple[Paper, ...]
    claims: tuple[ClaimReport, ...]
    findings: tuple[Finding, ...]
    models: RunModels | None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.models is None) != (self.provenance == "fake"):
            raise ValueError("models: required for a live report and absent from a fake one")
        by_id = {p.source_id: p for p in self.papers}
        if len(by_id) != len(self.papers):
            raise ValueError("papers: source ids must be unique")
        claim_ids = [c.claim.id for c in self.claims]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("claims: claim ids must be unique")
        not_retrieved: list[tuple[str, str]] = []
        for pair in (p for c in self.claims for p in c.pairs):
            result = pair.result
            paper = by_id.get(result.source_id)
            if isinstance(result, CitationNotRetrieved):
                if paper is not None:
                    raise ValueError(f"{result.source_id} was retrieved but is reported as not retrieved")
                not_retrieved.append((result.claim_id, result.source_id))
            elif paper is None:
                raise ValueError(f"{result.source_id} has a verifier outcome but was not retrieved")
            elif isinstance(result, Verdict):
                result.verify_against(paper.abstract)
        if unknown := sorted({f.claim_id for f in self.findings} - set(claim_ids)):
            raise ValueError(f"findings: name claims that are not in the report: {unknown}")
        invented = [
            (f.claim_id, f.source_id) for f in self.findings if f.kind is FindingKind.INVENTED_CITATION
        ]
        if invented != not_retrieved:
            raise ValueError("findings: invented citations must match the not-retrieved pairs, in order")
        if self.provenance == "fake":
            ids = [*by_id, *(s for c in self.claims for s in c.claim.cites)]
            if real := sorted({s for s in ids if not s.startswith(FAKE_PREFIX)}):
                raise ValueError(f"a fake report may cite only {FAKE_PREFIX} sources, got {real}")
        return self

    @computed_field
    @property
    def notice(self) -> str:
        """Printed first and stored in the artifact, so a fake report can never pass for a result and a
        live one says what its labels are."""
        return FAKE_NOTICE if self.provenance == "fake" else LIVE_NOTICE

    @computed_field
    @property
    def pair_counts(self) -> dict[Disposition, int]:
        return _counts([p.disposition for c in self.claims for p in c.pairs])

    @computed_field
    @property
    def claim_counts(self) -> dict[Disposition, int]:
        return _counts([c.disposition for c in self.claims])
