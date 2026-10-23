"""[RING:features/answer] `BaseAnswerer` backed by the two answer agents, one per mode.

Why: the use case depends on the port only; this answerer routes the mode to its agent and turns the
structured output into claims through `to_claims`, which assigns the ids and refuses citation defects
(I61). The port is unchanged, so `run_question` cannot tell it from the scripted answerer.
Must not: repair, filter or re-ask on a bad answer (a defect raises `answer.invalid_claims`), drop a
cite that was not retrieved (the invented-citation check reports it), or keep state between calls.
"""

from typing import override

from bio_claim_check.engine.agent.base_llm_agent import BaseLlmAgent
from bio_claim_check.features.answer.answer_models import AnswerOutput, AnswerPayload, to_claims
from bio_claim_check.features.answer.base_answerer import BaseAnswerer
from bio_claim_check.features.contracts.answer import Answer
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.contracts.paper import Paper

type AnswerAgent = BaseLlmAgent[AnswerPayload, AnswerOutput]


class LlmAnswerer(BaseAnswerer):
    """Answers with the Strict or the Over-eager agent, chosen by `mode`; `app` wires the agents."""

    def __init__(self, strict: AnswerAgent, over_eager: AnswerAgent) -> None:
        self._strict = strict
        self._over_eager = over_eager

    @override
    def answer(self, question: str, papers: tuple[Paper, ...], mode: AnswerMode) -> Answer:
        agent = self._strict if mode is AnswerMode.STRICT else self._over_eager
        result = agent.run(AnswerPayload(question=question, papers=papers))
        return Answer(question=question, mode=mode, claims=to_claims(result.output))
