"""[RING:features/answer] The Strict answer agent: answers only what the papers state, or abstains.

Why: the honest baseline the checker is measured against. It declares its prompt and output and
writes its variables; the agent base owns rendering, the request and the runner (ADR 0015).
Must not: hold prompt text (that is `answer_prompts`), turn its output into claims (that is
`to_claims`, called by `LlmAnswerer`), or keep state between runs.
"""

from collections.abc import Mapping
from typing import override

from bio_claim_check.engine.agent.base_llm_agent import BaseLlmAgent
from bio_claim_check.features.answer.answer_models import AnswerOutput, AnswerPayload
from bio_claim_check.features.answer.answer_prompts import STRICT_PROMPT, answer_variables


class StrictAnswerLlmAgent(BaseLlmAgent[AnswerPayload, AnswerOutput]):
    name = "answer_strict"
    prompt = STRICT_PROMPT
    output = AnswerOutput

    @override
    def variables(self, payload: AnswerPayload) -> Mapping[str, str]:
        return answer_variables(payload)
