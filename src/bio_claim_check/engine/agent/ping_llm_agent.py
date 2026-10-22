"""[RING:engine/agent] The connectivity probe behind `llm ping`: the first concrete `BaseLlmAgent`.

Why: before S10 spends money on real questions, one tiny structured call per deployment proves the
endpoint, the key, the pinned version, structured output (strict schema / forced tool) and usage
reporting all work, through the same agent base every real agent uses. It is feature-agnostic (it knows
no claims or papers), so it lives in the engine beside its base.
Must not: carry domain text or real data; the prompt is fixed and fictional, so a recording of it is
safe to commit as a fixture.
"""

from collections.abc import Mapping
from typing import override

from bio_claim_check.common.models import ValidatedModel
from bio_claim_check.engine.agent.base_llm_agent import BaseLlmAgent
from bio_claim_check.engine.prompts.prompt_template import PromptTemplate

PING_PROMPT = PromptTemplate(
    name="ping",
    version=1,
    system="You are a connectivity check. Reply only in the requested structured form.",
    user='This is a test message. Set "ok" to true.',
)


class PingReply(ValidatedModel):
    ok: bool


class PingLlmAgent(BaseLlmAgent[None, PingReply]):
    name = "ping"
    prompt = PING_PROMPT
    output = PingReply

    @override
    def variables(self, payload: None) -> Mapping[str, str]:
        return {}
