"""[RING:features/traps] A model panel's votes: unanimity, the committed ledger, and agreement counts.

Why: the maintainer is not a domain expert, so dev-v1 is confirmed by a panel of models from neither the
writer's nor the verifier's family (ADR 0023). A row is kept only if every rater confirmed it, and its
parent too. The ledger is committed beside the set: per candidate, each rater's vote, the draft, the
rater protocol's hash and the intended freeze. It lets CI recompute exactly which rows the set must hold,
so the panel's selection is attested, not self-reported. Agreement is counted per vote pattern (for two
raters, the 2x2 table), stratified by role and generator; no kappa (pairs are dependent, classes unbalanced).
Must not: hold a reason or a claim (reasons may quote an abstract, ADR 0008), look up a rater's family (the
app's closed registry does), or call a model.

No LLM is involved in this module.
"""

from collections import Counter
from collections.abc import Sequence
from itertools import product
from typing import Literal, Self

from pydantic import model_validator

from bio_claim_check.common.models import NonBlankStr, Sha256Hex, ValidatedModel
from bio_claim_check.features.contracts.ids import ClaimId
from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.traps.audit_sheet import TrapDecision, candidates
from bio_claim_check.features.traps.models import DraftRow, Generator, Role

Vote = Literal["confirm", "reject"]
VOTES: tuple[Vote, ...] = ("confirm", "reject")


class LedgerRow(ValidatedModel):
    """One candidate's votes, in the ledger's rater order. Metadata only: no claim, no reason."""

    id: ClaimId
    pair_id: ClaimId
    role: Role
    generator: Generator
    kind: OverstatedReason
    votes: tuple[Vote, ...]


class PanelLedger(ValidatedModel):
    """Who confirmed a set and how each rater voted on every candidate (ADR 0023, I79)."""

    set_sha256: Sha256Hex
    draft_sha256: Sha256Hex
    protocol_sha256: Sha256Hex
    intended_freeze: NonBlankStr
    raters: tuple[NonBlankStr, ...]
    sheet_sha256: tuple[Sha256Hex, ...]
    rows: tuple[LedgerRow, ...]

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if len(self.raters) < 2 or len(set(self.raters)) != len(self.raters):
            raise ValueError("raters: at least two, all distinct")
        if len(set(self.sheet_sha256)) != len(self.raters):
            raise ValueError("sheet_sha256: one distinct sheet per rater")
        if any(len(r.votes) != len(self.raters) for r in self.rows):
            raise ValueError("votes: one per rater on every row")
        ids = [r.id for r in self.rows]
        if ids != sorted(set(ids)):
            raise ValueError("rows: unique ids, sorted")
        parents = {r.id for r in self.rows if r.role == "parent"}
        if any(r.pair_id not in parents for r in self.rows):
            raise ValueError("rows: every pair_id names a parent row")
        return self


def unanimous(panels: Sequence[Sequence[TrapDecision]]) -> tuple[TrapDecision, ...]:
    """One decision per candidate: confirm only if every rater confirmed it.

    Every panel must decide the same ids in the same order (each came from `parse_decisions` on one draft).
    """
    if len(panels) < 2 or len({tuple(d.id for d in p) for p in panels}) != 1:
        raise ValueError("a panel needs at least two sheets deciding the same candidates")
    return tuple(
        TrapDecision(id=ds[0].id, decision="confirm", reason=None)
        if all(d.decision == "confirm" for d in ds)
        else TrapDecision(id=ds[0].id, decision="reject", reason="not unanimous")
        for ds in zip(*panels, strict=True)
    )


def ledger_rows(rows: Sequence[DraftRow], panels: Sequence[Sequence[TrapDecision]]) -> tuple[LedgerRow, ...]:
    """Every candidate's votes, sorted by id. Panels are in rater order."""
    votes: dict[str, list[Vote]] = {d.id: [d.decision] for d in panels[0]}
    for panel in panels[1:]:
        for d in panel:
            votes[d.id].append(d.decision)
    return tuple(
        sorted(
            (
                LedgerRow(
                    id=r.id,
                    pair_id=r.pair_id,
                    role=r.role,
                    generator=r.generator,
                    kind=r.kind,
                    votes=tuple(votes[r.id]),
                )
                for r in candidates(rows)
            ),
            key=lambda r: r.id,
        )
    )


def kept_ids(ledger: PanelLedger) -> frozenset[ClaimId]:
    """The ids the committed set must hold: unanimous rows whose parent is unanimous too."""
    yes = {r.id for r in ledger.rows if all(v == "confirm" for v in r.votes)}
    return frozenset(r.id for r in ledger.rows if r.id in yes and r.pair_id in yes)


def agreement(ledger: PanelLedger) -> tuple[tuple[Role, Generator, tuple[Vote, ...], int], ...]:
    """Every vote pattern's count, zeros included, per role and generator (for two raters, the 2x2 table)."""
    tally: Counter[tuple[Role, Generator, tuple[Vote, ...]]] = Counter(
        (r.role, r.generator, r.votes) for r in ledger.rows
    )
    strata: list[tuple[Role, Generator]] = sorted({(r.role, r.generator) for r in ledger.rows})
    patterns = sorted(product(VOTES, repeat=len(ledger.raters)))
    return tuple((role, gen, votes, tally[role, gen, votes]) for role, gen in strata for votes in patterns)


def percent_agreement(
    table: Sequence[tuple[Role, Generator, tuple[Vote, ...], int]],
) -> tuple[tuple[Role, Generator, int, int], ...]:
    """Per role and generator: rows on which every rater voted alike, out of all rows. No kappa (ADR 0023)."""
    totals: Counter[tuple[Role, Generator]] = Counter()
    agreed: Counter[tuple[Role, Generator]] = Counter()
    for role, gen, votes, n in table:
        totals[role, gen] += n
        agreed[role, gen] += n if len(set(votes)) == 1 else 0
    return tuple((role, gen, agreed[role, gen], n) for (role, gen), n in sorted(totals.items()))
