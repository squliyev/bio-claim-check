"""Trap counts (ADR 0022): predeclared caught, exact and false-alarm inputs; failures stay counted."""

import pytest
from pydantic import ValidationError
from tests.support.traps import parent, trap

from bio_claim_check.features.contracts.labels import (
    Disposition,
    EvidenceStatus,
    FailureKind,
    Label,
    NegationCheck,
    OverstatedReason,
)
from bio_claim_check.features.contracts.outcome import PairOutcome
from bio_claim_check.features.traps.audit_sheet import TrapDecision, confirmed_items
from bio_claim_check.features.traps.counts import CountRow, PairRow, TrapResult, counts, exact

ROWS = (parent(), trap(), trap(claim="Drug X raised plaque in mice.", rule="direction"))
ITEMS = confirmed_items(ROWS, tuple(TrapDecision(id=r.id, decision="confirm", reason=None) for r in ROWS))
BY_ROLE = {(i.role, i.generator): i for i in ITEMS}
KIND = OverstatedReason.PRECLINICAL_TO_CLINICAL


def _judged(
    item_id: str, label: Label, disposition: Disposition, reason: OverstatedReason | None = None
) -> PairOutcome:
    return PairOutcome(
        id=item_id,
        label=label,
        reason=reason,
        evidence_status=EvidenceStatus.LOCATED,
        negation=NegationCheck.CLEAR,
        disposition=disposition,
        failure_kind=None,
    )


def _failed(item_id: str) -> PairOutcome:
    return PairOutcome(
        id=item_id,
        label=None,
        reason=None,
        evidence_status=None,
        negation=None,
        disposition=Disposition.FAILED,
        failure_kind=FailureKind.STRUCTURED_OUTPUT,
    )


def test_exact_needs_the_expected_label_and_reason() -> None:
    model_trap, floor = BY_ROLE["trap", "model"], BY_ROLE["trap", "rule_floor"]
    assert exact(model_trap, _judged(model_trap.id, Label.OVERSTATED, Disposition.FLAGGED, KIND))
    assert not exact(
        model_trap,
        _judged(
            model_trap.id, Label.OVERSTATED, Disposition.FLAGGED, OverstatedReason.POPULATION_EXTRAPOLATION
        ),
    )
    assert not exact(model_trap, _judged(model_trap.id, Label.SUPPORTED, Disposition.PASSED))
    assert exact(floor, _judged(floor.id, Label.CONTRADICTED, Disposition.FLAGGED))
    assert exact(floor, _judged(floor.id, Label.NOT_IN_SOURCE, Disposition.FLAGGED))
    assert not exact(floor, _judged(floor.id, Label.OVERSTATED, Disposition.FLAGGED, KIND))


def test_counts_group_by_kind_role_and_generator_and_keep_failures() -> None:
    p, t, f = BY_ROLE["parent", "model"], BY_ROLE["trap", "model"], BY_ROLE["trap", "rule_floor"]
    outcomes = (
        _judged(p.id, Label.SUPPORTED, Disposition.PASSED),
        _failed(t.id),
        _judged(f.id, Label.CONTRADICTED, Disposition.FLAGGED),
    )
    rows = {(r.role, r.generator): r for r in counts(ITEMS, outcomes).rows}
    assert rows["parent", "model"].passed == 1
    assert rows["parent", "model"].exact == 1
    assert rows["trap", "model"].failed == 1
    assert rows["trap", "model"].n == 1
    assert rows["trap", "model"].exact == 0
    assert rows["trap", "rule_floor"].flagged == 1
    assert rows["trap", "rule_floor"].exact == 1


def test_outcomes_must_match_items_one_to_one() -> None:
    p = BY_ROLE["parent", "model"]
    one = _judged(p.id, Label.SUPPORTED, Disposition.PASSED)
    with pytest.raises(ValueError, match="exactly once"):
        counts(ITEMS, (one,))
    with pytest.raises(ValueError, match="exactly once"):
        counts(ITEMS[:1], (one, one))


def test_rows_must_add_up() -> None:
    fields = {
        "kind": KIND,
        "role": "trap",
        "generator": "model",
        "n": 2,
        "passed": 1,
        "needs_review": 0,
        "flagged": 0,
        "failed": 0,
        "exact": 0,
    }
    with pytest.raises(ValidationError, match="add up"):
        CountRow.model_validate(fields)
    with pytest.raises(ValidationError, match="exceed"):
        CountRow.model_validate({**fields, "n": 1, "exact": 2})


def test_results_are_sorted_one_per_item() -> None:
    p = BY_ROLE["parent", "model"]
    one = _judged(p.id, Label.SUPPORTED, Disposition.PASSED)
    base = {
        "trap_set_sha256": "a" * 64,
        "corpus_seal": "b" * 64,
        "judge_sha256": "c" * 64,
        "verifier": "v",
        "writer_family_flag": False,
        "counts": counts(ITEMS[:0], ()),
    }
    assert TrapResult.model_validate({**base, "outcomes": (one,)}).outcomes == (one,)
    with pytest.raises(ValidationError, match="sorted"):
        TrapResult.model_validate({**base, "outcomes": (one, one)})


def test_pair_tables_cross_each_trap_with_its_own_parent() -> None:
    p, t, f = BY_ROLE["parent", "model"], BY_ROLE["trap", "model"], BY_ROLE["trap", "rule_floor"]
    outcomes = (
        _judged(p.id, Label.SUPPORTED, Disposition.PASSED),
        _judged(t.id, Label.OVERSTATED, Disposition.FLAGGED, KIND),
        _failed(f.id),
    )
    pairs = {r.generator: r for r in counts(ITEMS, outcomes).pairs}
    assert set(pairs) == {"model", "rule_floor"}
    assert pairs["model"].n == 1
    assert pairs["model"].discriminated == 1
    assert pairs["rule_floor"].cell(Disposition.FAILED, Disposition.PASSED) == 1
    assert pairs["rule_floor"].discriminated == 0


def test_a_verifier_that_flags_everything_discriminates_nothing() -> None:
    outcomes = tuple(_judged(i.id, Label.CONTRADICTED, Disposition.FLAGGED) for i in ITEMS)
    for pair in counts(ITEMS, outcomes).pairs:
        assert pair.discriminated == 0
        assert pair.cell(Disposition.FLAGGED, Disposition.FLAGGED) == pair.n


def test_a_trap_without_its_parent_is_refused() -> None:
    t = BY_ROLE["trap", "model"]
    with pytest.raises(ValueError, match="no parent"):
        counts((t,), (_judged(t.id, Label.OVERSTATED, Disposition.FLAGGED, KIND),))


def test_pair_tables_must_be_square_and_add_up() -> None:
    zero = ((0, 0, 0, 0),) * 4
    fields = {"kind": KIND, "generator": "model", "n": 1}
    with pytest.raises(ValidationError, match="add up"):
        PairRow.model_validate({**fields, "table": zero})
    with pytest.raises(ValidationError, match="4 by 4"):
        PairRow.model_validate({**fields, "table": ((1,),)})
    with pytest.raises(ValidationError, match="negative"):
        PairRow.model_validate({**fields, "table": ((2, -1, 0, 0), *zero[1:])})
