"""[RING:features/answer] What the answer agents return, and the one way it becomes claims.

Why: the model's output carries only structure (claim text and cited ids), with no semantic validators.
The runner's single repair turn is spent on invalid JSON or a wrong shape only, so it can never be used
to talk a model out of a bad citation (it would launder it). `to_claims` then assigns the claim ids in
code and refuses any citation defect loudly (I61). A well-formed id that was not retrieved is kept as
is: the invented-citation check reports it, which is the measurement.
Must not: repair, drop or deduplicate a cite, renumber around a bad claim, or put claim text or ids in
an error message (errors are counted by defect only).

No LLM is involved in this module.
"""

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from pydantic import TypeAdapter, ValidationError

from bio_claim_check.common.errors import BccError
from bio_claim_check.common.models import ValidatedModel
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.verdict import Claim


class AnsweredClaim(ValidatedModel):
    """One claim as the model wrote it: its text and the ids it cites, in citation order."""

    text: str
    cites: tuple[str, ...]


class AnswerOutput(ValidatedModel):
    """The whole structured answer. No claims means the model abstained."""

    claims: tuple[AnsweredClaim, ...]


@dataclass(frozen=True, slots=True)
class AnswerPayload:
    """What an answer agent is asked: the question and the papers it may use, in rank order."""

    question: str
    papers: tuple[Paper, ...]


class ClaimDefect(StrEnum):
    """Why a claim from the model cannot become a `Claim`."""

    BLANK_TEXT = "blank_text"
    NO_CITES = "no_cites"
    DUPLICATE_CITE = "duplicate_cite"
    MALFORMED_CITE = "malformed_cite"


class AnswerClaimsError(BccError, ValueError):
    """The model's answer has claims that cannot be checked; it is refused, never repaired."""

    code = "answer.invalid_claims"

    def __init__(self, defects: Counter[ClaimDefect], claims: int) -> None:
        self.defects = defects
        counts = ", ".join(f"{d.value}={defects[d]}" for d in ClaimDefect if defects[d])
        super().__init__(f"the answer has {claims} claim(s) with defects: {counts}")


_SOURCE_ID: TypeAdapter[str] = TypeAdapter(SourceId)


def _defects(claim: AnsweredClaim) -> set[ClaimDefect]:
    found: set[ClaimDefect] = set()
    if not claim.text.strip():
        found.add(ClaimDefect.BLANK_TEXT)
    if not claim.cites:
        found.add(ClaimDefect.NO_CITES)
    if len(set(claim.cites)) != len(claim.cites):
        found.add(ClaimDefect.DUPLICATE_CITE)
    for cite in claim.cites:
        try:
            _SOURCE_ID.validate_python(cite)
        except ValidationError:
            found.add(ClaimDefect.MALFORMED_CITE)
    return found


def to_claims(output: AnswerOutput) -> tuple[Claim, ...]:
    """Claims `c1…cn` in answer order; raises `AnswerClaimsError` if any claim has any defect."""
    defects: Counter[ClaimDefect] = Counter()
    bad = 0
    for claim in output.claims:
        found = _defects(claim)
        defects.update(found)
        bad += bool(found)
    if bad:
        raise AnswerClaimsError(defects, bad)
    return tuple(
        Claim(id=f"c{i}", text=claim.text, cites=claim.cites) for i, claim in enumerate(output.claims, 1)
    )
