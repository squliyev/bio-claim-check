"""`LlmAnswerer`: routes the mode, keeps invented ids, and never repairs a citation (I61)."""

import pytest
from tests.support.llm import response, spec

from bio_claim_check.engine.llm.errors import LlmCallError
from bio_claim_check.engine.llm.scripted_llm_client import ScriptedLlmClient
from bio_claim_check.engine.prompts.prompt_template import PromptTemplate
from bio_claim_check.features.answer.answer_models import AnswerClaimsError
from bio_claim_check.features.answer.answer_prompts import OVER_EAGER_PROMPT, STRICT_PROMPT
from bio_claim_check.features.answer.llm_answerer import LlmAnswerer
from bio_claim_check.features.answer.over_eager_answer_llm_agent import OverEagerAnswerLlmAgent
from bio_claim_check.features.answer.strict_answer_llm_agent import StrictAnswerLlmAgent
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.contracts.verdict import Claim
from bio_claim_check.features.retrieval.in_memory_literature_source import FAKE_CORPUS

pytestmark = pytest.mark.unit

Q = "Does OS-912 work?"


def _answerer(*replies: str) -> tuple[LlmAnswerer, ScriptedLlmClient]:
    client = ScriptedLlmClient([response(r) for r in replies])
    return LlmAnswerer(StrictAnswerLlmAgent(client, spec()), OverEagerAnswerLlmAgent(client, spec())), client


@pytest.mark.parametrize(
    ("mode", "prompt"), [(AnswerMode.STRICT, STRICT_PROMPT), (AnswerMode.OVER_EAGER, OVER_EAGER_PROMPT)]
)
def test_the_mode_picks_the_agent(mode: AnswerMode, prompt: PromptTemplate) -> None:
    answerer, client = _answerer('{"claims": []}')
    answer = answerer.answer(Q, FAKE_CORPUS, mode)
    assert (answer.mode, answer.claims) == (mode, ())
    assert [r.prompt for r in client.requests] == [prompt.ref()]


def test_an_invented_but_well_formed_id_is_kept_for_the_check_to_report() -> None:
    answerer, _ = _answerer('{"claims": [{"text": "X works.", "cites": ["FAKE:1", "MED:99999999"]}]}')
    (claim,) = answerer.answer(Q, FAKE_CORPUS, AnswerMode.OVER_EAGER).claims
    assert claim == Claim(id="c1", text="X works.", cites=("FAKE:1", "MED:99999999"))


def test_a_citation_defect_is_refused_without_a_repair_turn() -> None:
    answerer, client = _answerer(
        '{"claims": [{"text": "X works.", "cites": ["[1]"]}]}',
        '{"claims": [{"text": "X works.", "cites": ["FAKE:1"]}]}',
    )
    with pytest.raises(AnswerClaimsError, match="malformed_cite=1"):
        answerer.answer(Q, FAKE_CORPUS, AnswerMode.STRICT)
    assert len(client.requests) == 1


def test_the_one_repair_is_spent_on_shape_only() -> None:
    answerer, client = _answerer(
        '{"claims": "none"}', '{"claims": [{"text": "X works.", "cites": ["FAKE:1"]}]}'
    )
    assert [c.id for c in answerer.answer(Q, FAKE_CORPUS, AnswerMode.STRICT).claims] == ["c1"]
    assert len(client.requests) == 2


def test_a_second_bad_shape_fails_the_call() -> None:
    answerer, _ = _answerer('{"claims": "none"}', "not json")
    with pytest.raises(LlmCallError):
        answerer.answer(Q, FAKE_CORPUS, AnswerMode.STRICT)
