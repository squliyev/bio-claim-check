"""[RING:features/traps] What a verifier did on the trap set: dispositions per kind, role and generator.

Why: the proof checkpoint reads these counts to decide whether the verifier is worth showing. They are
predeclared in ADR 0022 before any trap is verified: **caught** = a trap's disposition is `flagged`;
**exact** = also the expected label and reason (a rule-floor trap: `contradicted` or `not_in_source`);
**false alarm** = a parent's disposition is `flagged`. `needs_review` and `failed` have their own columns
and stay in the denominator (a failed trap is not caught). The paired design (ADR 0022 §5) is read from
**pair tables** (ADR 0024, before any trap was verified): per (kind, generator), every trap against its own
parent, as a full table of trap disposition by parent disposition. **Discriminated** = trap `flagged` and
parent `passed`. A parent shared by a model trap and a rule-floor trap appears in both generators' tables,
so the tables are descriptive and their pairs are not independent observations. Counts only: rates and
intervals belong to the benchmark (S16), and every number here is exploratory dev evidence. CI
recomputes the counts, pair tables included, in every committed results file (I76).
Must not: drop an item, tune anything, or hold claim or reason text (ADR 0008).

No LLM is involved in this module.
"""

from collections.abc import Mapping, Sequence
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


DISPOSITIONS: Final = (
    Disposition.PASSED,
    Disposition.NEEDS_REVIEW,
    Disposition.FLAGGED,
    Disposition.FAILED,
)
"""The fixed row and column order of a pair table."""


class PairRow(ValidatedModel):
    """Every trap of one (kind, generator) against its parent: `table[trap][parent]`, `DISPOSITIONS` order."""

    kind: OverstatedReason
    generator: Generator
    n: int = Field(strict=True, ge=1)
    table: tuple[tuple[int, ...], ...]

    @model_validator(mode="after")
    def _square_and_adds_up(self) -> Self:
        size = len(DISPOSITIONS)
        if len(self.table) != size or any(len(row) != size for row in self.table):
            raise ValueError(f"a pair table is {size} by {size}")
        if any(cell < 0 for row in self.table for cell in row):
            raise ValueError("pair table cells cannot be negative")
        if sum(map(sum, self.table)) != self.n:
            raise ValueError("pair table cells must add up to n")
        return self

    def cell(self, trap: Disposition, parent: Disposition) -> int:
        return self.table[DISPOSITIONS.index(trap)][DISPOSITIONS.index(parent)]

    @property
    def discriminated(self) -> int:
        """The trap was flagged and its parent passed."""
        return self.cell(Disposition.FLAGGED, Disposition.PASSED)


class TrapCounts(ValidatedModel):
    rows: tuple[CountRow, ...]
    pairs: tuple[PairRow, ...]


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
    return TrapCounts(rows=tuple(rows), pairs=_pairs(items, by_id))


def _pairs(items: Sequence[TrapItem], by_id: Mapping[str, PairOutcome]) -> tuple[PairRow, ...]:
    """One pair table per (kind, generator) of the traps, sorted; every trap's parent must be an item."""
    parents = {i.id: i for i in items if i.role == "parent"}
    groups: dict[tuple[OverstatedReason, Generator], list[TrapItem]] = {}
    for item in items:
        if item.role != "trap":
            continue
        if item.pair_id not in parents:
            raise ValueError(f"trap {item.id} has no parent among the items")
        groups.setdefault((item.kind, item.generator), []).append(item)
    rows: list[PairRow] = []
    for (kind, generator), group in sorted(groups.items()):
        table = [[0] * len(DISPOSITIONS) for _ in DISPOSITIONS]
        for item in group:
            t = DISPOSITIONS.index(by_id[item.id].disposition)
            p = DISPOSITIONS.index(by_id[item.pair_id].disposition)
            table[t][p] += 1
        rows.append(PairRow(kind=kind, generator=generator, n=len(group), table=tuple(map(tuple, table))))
    return tuple(rows)


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
