"""A model panel (ADR 0023): unanimous only, a parent gates its traps, a well-formed and counted ledger."""

import pytest
from pydantic import ValidationError
from tests.support.traps import parent, trap

from bio_claim_check.features.traps.audit_sheet import TrapDecision, candidates
from bio_claim_check.features.traps.panel import (
    LedgerRow,
    PanelLedger,
    agreement,
    kept_ids,
    ledger_rows,
    percent_agreement,
    unanimous,
)

pytestmark = pytest.mark.unit

ROWS = (
    parent("MED:1"),
    trap("MED:1"),
    trap("MED:1", "Drug X raised plaque in mice.", rule="direction"),
    parent("MED:2", "Y helped rats."),
    trap("MED:2", "Y helps people."),
)
IDS = [r.id for r in candidates(ROWS)]
P1, T1, F1, P2, T2 = (ROWS[0].id, ROWS[1].id, ROWS[2].id, ROWS[3].id, ROWS[4].id)


def _panel(reject: set[str]) -> tuple[TrapDecision, ...]:
    return tuple(
        TrapDecision(id=i, decision="reject", reason="no")
        if i in reject
        else TrapDecision(id=i, decision="confirm", reason=None)
        for i in IDS
    )


def _ledger(a: set[str], b: set[str]) -> PanelLedger:
    return PanelLedger(
        set_sha256="a" * 64,
        draft_sha256="b" * 64,
        protocol_sha256="c" * 64,
        intended_freeze="v2",
        raters=("gemini-4-argon", "grok-4.7"),
        sheet_sha256=("d" * 64, "e" * 64),
        rows=ledger_rows(ROWS, [_panel(a), _panel(b)]),
    )


def test_a_row_is_confirmed_only_if_every_rater_confirmed_it() -> None:
    decided = {d.id: d.decision for d in unanimous([_panel({T1}), _panel({F1})])}
    assert decided == {P1: "confirm", T1: "reject", F1: "reject", P2: "confirm", T2: "confirm"}


def test_a_panel_needs_two_sheets_on_the_same_candidates() -> None:
    with pytest.raises(ValueError, match="at least two"):
        unanimous([_panel(set())])
    with pytest.raises(ValueError, match="same candidates"):
        unanimous([_panel(set()), _panel(set())[1:]])


def test_kept_ids_drop_a_trap_whose_parent_one_rater_rejected() -> None:
    assert kept_ids(_ledger({P2}, set())) == {P1, T1, F1}
    assert kept_ids(_ledger(set(), {T1})) == {P1, F1, P2, T2}


def test_the_ledger_holds_every_candidates_votes_in_rater_order_and_no_text() -> None:
    ledger = _ledger({T1}, set())
    assert [r.id for r in ledger.rows] == sorted(IDS)
    assert {r.id: r.votes for r in ledger.rows}[T1] == ("reject", "confirm")
    assert set(LedgerRow.model_fields) == {"id", "pair_id", "role", "generator", "kind", "votes"}


def test_agreement_counts_each_vote_pattern_per_role_and_generator() -> None:
    table = agreement(_ledger({T1}, {T2}))
    cc, cr, rc, rr = (
        ("confirm", "confirm"),
        ("confirm", "reject"),
        ("reject", "confirm"),
        ("reject", "reject"),
    )
    assert table == (
        ("parent", "model", cc, 2),
        ("parent", "model", cr, 0),
        ("parent", "model", rc, 0),
        ("parent", "model", rr, 0),
        ("trap", "model", cc, 0),
        ("trap", "model", cr, 1),
        ("trap", "model", rc, 1),
        ("trap", "model", rr, 0),
        ("trap", "rule_floor", cc, 1),
        ("trap", "rule_floor", cr, 0),
        ("trap", "rule_floor", rc, 0),
        ("trap", "rule_floor", rr, 0),
    )
    assert percent_agreement(table) == (
        ("parent", "model", 2, 2),
        ("trap", "model", 0, 2),
        ("trap", "rule_floor", 1, 1),
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"raters": ("gemini-4-argon",), "sheet_sha256": ("d" * 64,)}, "at least two"),
        ({"raters": ("grok-4.7", "grok-4.7")}, "at least two"),
        ({"sheet_sha256": ("d" * 64,)}, "one distinct sheet per rater"),
        ({"sheet_sha256": ("d" * 64, "d" * 64)}, "one distinct sheet per rater"),
    ],
)
def test_a_malformed_ledger_is_invalid(change: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        PanelLedger.model_validate({**_ledger(set(), set()).model_dump(), **change})


def test_ledger_rows_must_be_sorted_one_vote_per_rater_and_name_their_parent() -> None:
    good = _ledger(set(), set()).model_dump()
    rows = good["rows"]
    with pytest.raises(ValidationError, match="sorted"):
        PanelLedger.model_validate({**good, "rows": list(reversed(rows))})
    with pytest.raises(ValidationError, match="one per rater"):
        PanelLedger.model_validate({**good, "rows": [{**rows[0], "votes": ("confirm",)}, *rows[1:]]})
    orphans = [r for r in rows if r["role"] == "trap"]
    with pytest.raises(ValidationError, match="names a parent"):
        PanelLedger.model_validate({**good, "rows": orphans})
