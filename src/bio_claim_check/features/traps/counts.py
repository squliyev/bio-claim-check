"""[RING:features/traps] What a verifier did on the trap set: dispositions per kind, role and generator.

Why: the proof checkpoint reads these counts to decide whether the verifier is worth showing. They are
predeclared in ADR 0022 before any trap is verified: **caught** = a trap's disposition is `flagged`;
**exact** = also the expected label and reason (a rule-floor trap: `contradicted` or `not_in_source`);
**false alarm** = a parent's disposition is `flagged`. `needs_review` and `failed` have their own columns
and stay in the denominator (a failed trap is not caught). Counts only: rates and intervals belong to the
benchmark (S16), and every number here is exploratory dev evidence. CI recomputes the counts in every
committed results file (I76).
Must not: drop an item, tune anything, or hold claim or reason text (ADR 0008).

No LLM is involved in this module.
"""

from collections.abc import Sequence
from typing import Final, Self

from pydantic import Field, model_validator

from bio_claim_check.common.models import NonBlankStr, Sha256Hex, ValidatedModel
from bio_claim_check.features.contracts.labels import Disposition, Label, OverstatedReason
from bio_claim_check.features.contracts.outcome import PairOutcome
from bio_claim_check.features.traps.models import Generator, Role, TrapItem

FLOOR_LABELS: Final = frozenset({Label.CONTRADICTED, Label.NOT_IN_SOURCE})


class CountRow(ValidatedModel):
    """Dispositions of every item sharing one (kind, role, generator)."""

    kind: OverstatedReason
    role: Role
    generator: Generator
    n: int = Field(strict=True, ge=1)
    passed: int = Field(strict=True, ge=0)
    needs_review: int = Field(strict=True, ge=0)
    flagged: int = Field(strict=True, ge=0)
    failed: int = Field(strict=True, ge=0)
    exact: int = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def _adds_up(self) -> Self:
        if self.passed + self.needs_review + self.flagged + self.failed != self.n:
            raise ValueError("dispositions must add up to n")
        if self.exact > self.n:
            raise ValueError("exact cannot exceed n")
        return self


class TrapCounts(ValidatedModel):
    rows: tuple[CountRow, ...]


def exact(item: TrapItem, outcome: PairOutcome) -> bool:
    """The verifier reached the expected disposition, label and reason."""
    if outcome.disposition is not item.expected_disposition:
        return False
    if item.expected_label is None:
        return outcome.label in FLOOR_LABELS
    return outcome.label is item.expected_label and outcome.reason is item.expected_reason


def counts(items: Sequence[TrapItem], outcomes: Sequence[PairOutcome]) -> TrapCounts:
    """One row per (kind, role, generator) present, sorted; outcomes must match items one to one."""
    by_id = {o.id: o for o in outcomes}
    if len(by_id) != len(outcomes) or set(by_id) != {i.id for i in items} or len(items) != len(by_id):
        raise ValueError("outcomes must name every item exactly once")
    groups: dict[tuple[OverstatedReason, Role, Generator], list[TrapItem]] = {}
    for item in items:
        groups.setdefault((item.kind, item.role, item.generator), []).append(item)
    rows: list[CountRow] = []
    for (kind, role, generator), group in sorted(groups.items()):
        dispositions = [by_id[i.id].disposition for i in group]
        rows.append(
            CountRow(
                kind=kind,
                role=role,
                generator=generator,
                n=len(group),
                passed=dispositions.count(Disposition.PASSED),
                needs_review=dispositions.count(Disposition.NEEDS_REVIEW),
                flagged=dispositions.count(Disposition.FLAGGED),
                failed=dispositions.count(Disposition.FAILED),
                exact=sum(exact(i, by_id[i.id]) for i in group),
            )
        )
    return TrapCounts(rows=tuple(rows))


class TrapResult(ValidatedModel):
    """`traps/results/<freeze>-<set>.json`: one verifier run over one committed trap set (ADR 0022)."""

    trap_set_sha256: Sha256Hex
    corpus_seal: Sha256Hex
    judge_sha256: Sha256Hex
    verifier: NonBlankStr
    writer_family_flag: bool = Field(strict=True)
    """True when the trap writer and the verifier are the same model family (a disclosed bias)."""
    outcomes: tuple[PairOutcome, ...]
    counts: TrapCounts

    @model_validator(mode="after")
    def _sorted(self) -> Self:
        ids = [o.id for o in self.outcomes]
        if ids != sorted(set(ids)):
            raise ValueError("outcomes: one per item, sorted by id")
        return self
