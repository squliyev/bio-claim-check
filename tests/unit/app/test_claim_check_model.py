import json
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError
from tests.support.checks import CLAIM_TEXT, PMID, live_check_ports

from bio_claim_check.app.container import build_fake_check_ports, fake_check_claims
from bio_claim_check.app.usecases.check_claim import check_claim, live_claim
from bio_claim_check.features.report.canonical import canonical_bytes
from bio_claim_check.features.report.models import ClaimCheck


def _live() -> dict[str, Any]:
    return json.loads(canonical_bytes(check_claim(live_check_ports(), live_claim(CLAIM_TEXT, PMID))))


def _fake(example: str = "o1") -> dict[str, Any]:
    claim = next(c for c in fake_check_claims() if c.id == example)
    return json.loads(canonical_bytes(check_claim(build_fake_check_ports(), claim)))


def test_a_check_round_trips_byte_for_byte() -> None:
    for data in (_live(), _fake(), _fake("o6")):
        assert canonical_bytes(ClaimCheck.model_validate(data)) == canonical_bytes(
            ClaimCheck.model_validate_json(json.dumps(data))
        )
        assert json.loads(canonical_bytes(ClaimCheck.model_validate(data))) == data


def _set(path: tuple[str | int, ...], value: object) -> Callable[[dict[str, Any]], None]:
    def change(data: dict[str, Any]) -> None:
        node: Any = data
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return change


@pytest.mark.parametrize(
    ("build", "change", "message"),
    [
        (_live, _set(("verifier",), None), "verifier: required"),
        (_fake, _set(("verifier",), {"deployment": "m", "family": "openai"}), "verifier: required"),
        (_live, _set(("provenance",), "fake"), "notice: stored value does not match"),
        (_live, _set(("claim", "claim", "cites"), ["MED:1"]), "no outcome for cited sources"),
        (_live, _set(("paper", "source_id"), "MED:1"), "cites exactly the paper"),
        (
            _live,
            _set(("claim", "pairs", 0, "verdict", "evidence_span"), {"start": 0, "end": 5}),
            "does not match the abstract",
        ),
        (_live, _set(("notice",), "A result."), "notice: stored value does not match"),
        (_live, _set(("claim", "disposition"), "supported"), "disposition: stored value does not match"),
    ],
)
def test_a_tampered_check_is_refused(
    build: Callable[[], dict[str, Any]], change: Callable[[dict[str, Any]], None], message: str
) -> None:
    data = build()
    change(data)
    with pytest.raises(ValidationError, match=message):
        ClaimCheck.model_validate(data)


def test_a_check_has_exactly_one_pair() -> None:
    data = _live()
    data["claim"]["pairs"] = data["claim"]["pairs"] * 2
    with pytest.raises(ValidationError):
        ClaimCheck.model_validate(data)


def test_a_fake_check_may_cite_only_fictional_papers() -> None:
    data = _live()
    data["provenance"], data["verifier"] = "fake", None
    del data["notice"]
    with pytest.raises(ValidationError, match="may cite only FAKE:"):
        ClaimCheck.model_validate(data)


def test_a_checked_paper_cannot_be_not_retrieved() -> None:
    data = _live()
    source_id = data["paper"]["source_id"]
    data["claim"]["pairs"] = [
        {"outcome": "citation_not_retrieved", "citation": {"claim_id": "c1", "source_id": source_id}}
    ]
    del data["claim"]["disposition"]
    with pytest.raises(ValidationError, match="cannot be not retrieved"):
        ClaimCheck.model_validate(data)
