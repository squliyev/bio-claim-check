"""[TEST SUPPORT] Draft rows and trap items built the way generation builds them."""

from bio_claim_check.features.contracts.labels import FailureKind, OverstatedReason
from bio_claim_check.features.traps.models import DraftRow, FloorRule, opaque_id

KIND = OverstatedReason.PRECLINICAL_TO_CLINICAL
SHA = "b" * 64
DEPLOYMENT = "writer-deployment"


def parent(
    source_id: str = "MED:1",
    claim: str | None = "Drug X lowered plaque in mice.",
    *,
    problems: tuple[str, ...] = (),
    failure: FailureKind | None = None,
) -> DraftRow:
    pid = opaque_id(source_id, "parent", None)
    return DraftRow(
        id=pid,
        pair_id=pid,
        role="parent",
        kind=KIND,
        question_id="a-q1",
        source_id=source_id,
        abstract_sha256=SHA,
        claim=claim,
        generator="model",
        rule=None,
        origin_id=DEPLOYMENT,
        problems=problems,
        failure=failure,
    )


def trap(
    source_id: str = "MED:1",
    claim: str | None = "Drug X lowers plaque in patients.",
    *,
    rule: FloorRule | None = None,
    problems: tuple[str, ...] = (),
    failure: FailureKind | None = None,
) -> DraftRow:
    return DraftRow(
        id=opaque_id(source_id, "trap", rule),
        pair_id=opaque_id(source_id, "parent", None),
        role="trap",
        kind=KIND,
        question_id="a-q1",
        source_id=source_id,
        abstract_sha256=SHA,
        claim=claim,
        generator="rule_floor" if rule else "model",
        rule=rule,
        origin_id=DEPLOYMENT,
        problems=problems,
        failure=failure,
    )
