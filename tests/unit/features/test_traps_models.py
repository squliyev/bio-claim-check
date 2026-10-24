"""Trap records (ADR 0022): opaque ids, predeclared ground truth, and consistent draft rows."""

import pytest
from pydantic import ValidationError
from tests.support.traps import KIND, SHA, parent, trap

from bio_claim_check.features.contracts.labels import Disposition, FailureKind, Label
from bio_claim_check.features.traps.models import MAX_CLAIM_WORDS, TrapItem, expected_truth, opaque_id


def _item(**changes: object) -> TrapItem:
    pid = opaque_id("MED:1", "parent", None)
    fields: dict[str, object] = {
        "id": opaque_id("MED:1", "trap", None),
        "pair_id": pid,
        "role": "trap",
        "kind": KIND,
        "question_id": "a-q1",
        "source_id": "MED:1",
        "abstract_sha256": SHA,
        "claim": "X helps patients.",
        "expected_disposition": Disposition.FLAGGED,
        "expected_label": Label.OVERSTATED,
        "expected_reason": KIND,
        "generator": "model",
        "rule": None,
        "origin": "model",
        "origin_id": "dep",
        "confirmed_by": "author",
    }
    return TrapItem.model_validate({**fields, **changes})


def test_ids_are_opaque_stable_and_distinct_per_role_and_rule() -> None:
    ids = {
        opaque_id("MED:1", "parent", None),
        opaque_id("MED:1", "trap", None),
        opaque_id("MED:1", "trap", "dose"),
        opaque_id("MED:2", "parent", None),
    }
    assert len(ids) == 4
    assert all(i.startswith("t") and len(i) == 12 and "MED" not in i for i in ids)
    assert opaque_id("MED:1", "trap", None) == opaque_id("MED:1", "trap", None)


def test_ground_truth_is_predeclared() -> None:
    assert expected_truth("parent", "model", KIND) == (Disposition.PASSED, Label.SUPPORTED, None)
    assert expected_truth("trap", "model", KIND) == (Disposition.FLAGGED, Label.OVERSTATED, KIND)
    assert expected_truth("trap", "rule_floor", KIND) == (Disposition.FLAGGED, None, None)


def test_a_valid_item_validates() -> None:
    assert _item().role == "trap"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"claim": " ".join(["w"] * (MAX_CLAIM_WORDS + 1))}, "at most"),
        ({"claim": "padded "}, "whitespace"),
        ({"id": "t000000000000"}, "opaque id"),
        ({"generator": "rule_floor"}, "rule:"),
        ({"expected_label": Label.CONTRADICTED}, "ground truth"),
        (
            {
                "role": "parent",
                "id": opaque_id("MED:1", "parent", None),
                "pair_id": "t1",
                "expected_disposition": Disposition.PASSED,
                "expected_label": Label.SUPPORTED,
                "expected_reason": None,
            },
            "own pair",
        ),
    ],
)
def test_an_inconsistent_item_is_refused(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _item(**changes)


def test_draft_rows_are_consistent() -> None:
    assert parent().candidate
    assert not parent(problems=("too long",)).candidate
    assert not parent(claim=None, failure=FailureKind.STRUCTURED_OUTPUT).candidate
    with pytest.raises(ValidationError, match="writer failed"):
        parent(claim=None)
    with pytest.raises(ValidationError, match="writer failed"):
        parent(failure=FailureKind.STRUCTURED_OUTPUT)
    with pytest.raises(ValidationError, match="rule:"):
        trap().model_validate({**trap().model_dump(), "generator": "rule_floor"})
    with pytest.raises(ValidationError, match="own pair"):
        parent().model_validate({**parent().model_dump(), "pair_id": "t1"})
