"""`to_claims`: ids come from code; a citation defect is refused, never repaired (I61)."""

import pytest

from bio_claim_check.engine.llm.codec_support import strict_schema_problems
from bio_claim_check.features.answer.answer_models import (
    AnswerClaimsError,
    AnsweredClaim,
    AnswerOutput,
    ClaimDefect,
    to_claims,
)
from bio_claim_check.features.contracts.verdict import Claim

pytestmark = pytest.mark.unit


def _out(*claims: tuple[str, tuple[str, ...]]) -> AnswerOutput:
    return AnswerOutput(claims=tuple(AnsweredClaim(text=t, cites=c) for t, c in claims))


def test_ids_are_assigned_in_answer_order_and_cites_kept_verbatim() -> None:
    claims = to_claims(_out(("A lowers B.", ("MED:1", "MED:9")), ("C raises D.", ("PMC:PMC7",))))
    assert claims == (
        Claim(id="c1", text="A lowers B.", cites=("MED:1", "MED:9")),
        Claim(id="c2", text="C raises D.", cites=("PMC:PMC7",)),
    )


def test_an_abstention_is_no_claims() -> None:
    assert to_claims(_out()) == ()


@pytest.mark.parametrize(
    ("claim", "defect"),
    [
        pytest.param((" ", ("MED:1",)), ClaimDefect.BLANK_TEXT, id="blank"),
        pytest.param(("A lowers B.", ()), ClaimDefect.NO_CITES, id="no-cites"),
        pytest.param(("A lowers B.", ("MED:1", "MED:1")), ClaimDefect.DUPLICATE_CITE, id="duplicate"),
        pytest.param(("A lowers B.", ("PMID 123",)), ClaimDefect.MALFORMED_CITE, id="malformed"),
        pytest.param(("A lowers B.", ("med:1",)), ClaimDefect.MALFORMED_CITE, id="lower-namespace"),
        pytest.param(("A lowers B.", ("[1]",)), ClaimDefect.MALFORMED_CITE, id="numbered"),
    ],
)
def test_each_defect_is_refused(claim: tuple[str, tuple[str, ...]], defect: ClaimDefect) -> None:
    with pytest.raises(AnswerClaimsError, match=f"1 claim\\(s\\) with defects: {defect.value}=1$") as caught:
        to_claims(_out(("Fine claim.", ("MED:2",)), claim))
    assert caught.value.code == "answer.invalid_claims"
    assert dict(caught.value.defects) == {defect: 1}


def test_defects_are_counted_per_claim_and_the_message_carries_no_text() -> None:
    sentinel = "SENTINEL-claim-text"
    output = _out((sentinel, ("bad id", "worse id")), (" ", ()), (sentinel, ("MED:1", "MED:1", "x")))
    with pytest.raises(AnswerClaimsError) as caught:
        to_claims(output)
    message = str(caught.value)
    assert message == (
        "the answer has 3 claim(s) with defects: blank_text=1, no_cites=1, duplicate_cite=1, malformed_cite=2"
    )
    assert sentinel not in message
    assert "bad id" not in message


def test_the_output_schema_is_strict_and_has_no_semantic_rules() -> None:
    """Nothing in the schema or model can reject a cite, so the runner's repair never touches citations."""
    schema = AnswerOutput.model_json_schema(mode="validation")
    assert strict_schema_problems(schema) == ()
    accepted = AnswerOutput.model_validate_json(
        '{"claims": [{"text": " ", "cites": ["not an id", "not an id"]}]}'
    )
    assert accepted.claims[0].cites == ("not an id", "not an id")
