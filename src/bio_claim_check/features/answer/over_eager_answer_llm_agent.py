"""[RING:features/answer] The Over-eager answer agent: always answers, confidently, from the papers.

Why: the deliberate stress mode. It drops caveats and draws out implications, so the checks and the
verifier have overstatement to catch; it still cites only the given papers. It declares its prompt and
output and writes its variables; the agent base owns the rest (ADR 0015).
Must not: hold prompt text (that is `answer_prompts`), turn its output into claims (that is
`to_claims`, called by `LlmAnswerer`), or keep state between runs.
"""

from collections.abc import Mapping
from typing import override

from bio_claim_check.engine.agent.base_llm_agent import BaseLlmAgent
from bio_claim_check.features.answer.answer_models import AnswerOutput, AnswerPayload
from bio_claim_check.features.answer.answer_prompts import OVER_EAGER_PROMPT, answer_variables


class OverEagerAnswerLlmAgent(BaseLlmAgent[AnswerPayload, AnswerOutput]):
    name = "answer_over_eager"
    prompt = OVER_EAGER_PROMPT
    output = AnswerOutput

    @override
    def variables(self, payload: AnswerPayload) -> Mapping[str, str]:
        return answer_variables(payload)
