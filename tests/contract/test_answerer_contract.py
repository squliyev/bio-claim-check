"""Every answerer echoes its question and mode, with unique claim ids that each cite a source (I33).

`run_question` cannot tell one answerer from another, so each must keep the same promises.
"""

from collections.abc import Callable

import pytest

from bio_claim_check.engine.llm.scripted_llm_client import ScriptedLlmClient
from bio_claim_check.features.answer.base_answerer import BaseAnswerer
from bio_claim_check.features.answer.llm_answerer import LlmAnswerer
from bio_claim_check.features.answer.over_eager_answer_llm_agent import OverEagerAnswerLlmAgent
from bio_claim_check.features.answer.scripted_answerer import ScriptedAnswerer
from bio_claim_check.features.answer.strict_answer_llm_agent import StrictAnswerLlmAgent
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.retrieval.in_memory_literature_source import FAKE_CORPUS
from tests.support.llm import response, spec

pytestmark = pytest.mark.contract

REPLY = (
    '{"claims": [{"text": "OS-912 reduced plaque in mice.", "cites": ["FAKE:1"]}, '
    '{"text": "HX-15 did not change scores.", "cites": ["FAKE:2", "FAKE:99"]}]}'
)


def _llm() -> LlmAnswerer:
    client = ScriptedLlmClient([response(REPLY)] * 4)
    return LlmAnswerer(StrictAnswerLlmAgent(client, spec()), OverEagerAnswerLlmAgent(client, spec()))


IMPLEMENTATIONS: tuple[type[BaseAnswerer], ...] = (ScriptedAnswerer, LlmAnswerer)
BUILD: dict[type[BaseAnswerer], Callable[[], BaseAnswerer]] = {
    ScriptedAnswerer: ScriptedAnswerer,
    LlmAnswerer: _llm,
}


@pytest.fixture(params=IMPLEMENTATIONS, ids=lambda cls: cls.__name__)
def answerer(request: pytest.FixtureRequest) -> BaseAnswerer:
    return BUILD[request.param]()


@pytest.mark.parametrize("mode", list(AnswerMode))
def test_the_answer_echoes_question_and_mode(answerer: BaseAnswerer, mode: AnswerMode) -> None:
    answer = answerer.answer("Does OS-912 work?", FAKE_CORPUS, mode)
    assert (answer.question, answer.mode) == ("Does OS-912 work?", mode)


@pytest.mark.parametrize("mode", list(AnswerMode))
def test_claims_have_unique_ids_and_cite_at_least_one_source(
    answerer: BaseAnswerer, mode: AnswerMode
) -> None:
    claims = answerer.answer("Does OS-912 work?", FAKE_CORPUS, mode).claims
    assert claims
    assert len({c.id for c in claims}) == len(claims)
    assert all(c.cites for c in claims)
