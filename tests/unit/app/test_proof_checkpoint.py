"""ADR 0024: code produces the dev-v1 go/adjust verdict at its exact thresholds, and fails closed."""

import pytest

from bio_claim_check.app.usecases.proof_checkpoint import (
    DEV_V1_SHA256,
    CheckpointError,
    Verdict,
    checkpoint,
    describe,
)
from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.traps.counts import CountRow, TrapCounts, TrapResult
from bio_claim_check.features.traps.models import Generator, Role

KIND = OverstatedReason.CORRELATION_AS_CAUSATION


def _row(
    role: Role, generator: Generator, n: int, *, flagged: int = 0, failed: int = 0, nr: int = 0
) -> CountRow:
    return CountRow(
        kind=KIND,
        role=role,
        generator=generator,
        n=n,
        passed=n - flagged - failed - nr,
        needs_review=nr,
        flagged=flagged,
        failed=failed,
        exact=0,
    )


def _result(
    *,
    traps_flagged: int = 10,
    parents_flagged: int = 3,
    parents_review: int = 1,
    failed: int = 2,
    sha: str = DEV_V1_SHA256,
    floor: int = 7,
) -> TrapResult:
    rows = (
        _row("parent", "model", 16, flagged=parents_flagged, nr=parents_review),
        _row("trap", "model", 15, flagged=traps_flagged, failed=failed),
        _row("trap", "rule_floor", floor),
    )
    return TrapResult(
        trap_set_sha256=sha,
        corpus_seal="b" * 64,
        judge_sha256="c" * 64,
        verifier="v",
        writer_family_flag=False,
        outcomes=(),
        counts=TrapCounts(rows=rows, pairs=()),
    )


def test_go_exactly_at_every_threshold() -> None:
    point = checkpoint(_result())
    assert (point.model_traps_flagged, point.parents_passed, point.parents_flagged, point.failed) == (
        10,
        12,
        3,
        2,
    )
    assert point.verdict is Verdict.GO
    assert "GO" in describe(point)
    assert "adr-0024-v1" in describe(point)


@pytest.mark.parametrize(
    ("traps_flagged", "parents_flagged", "parents_review", "failed"),
    [(9, 3, 1, 2), (10, 4, 0, 2), (10, 0, 5, 2), (10, 3, 1, 3)],
    ids=["traps-missed", "false-alarms", "parents-unresolved", "failures"],
)
def test_one_threshold_missed_is_adjust(
    traps_flagged: int, parents_flagged: int, parents_review: int, failed: int
) -> None:
    result = _result(
        traps_flagged=traps_flagged,
        parents_flagged=parents_flagged,
        parents_review=parents_review,
        failed=failed,
    )
    assert checkpoint(result).verdict is Verdict.ADJUST


def test_another_set_is_refused() -> None:
    with pytest.raises(CheckpointError, match="dev-v1 only"):
        checkpoint(_result(sha="a" * 64))


def test_other_denominators_are_refused() -> None:
    with pytest.raises(CheckpointError, match="should have"):
        checkpoint(_result(floor=8))
