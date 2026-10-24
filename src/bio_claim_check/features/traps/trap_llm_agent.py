"""[RING:features/traps] The trap writer agent: drafts one (parent, trap) pair for one abstract.

Why: the LLM half of trap generation. It declares its prompt and output and writes its variables; the
agent base owns rendering, the request and the runner (ADR 0015).
Must not: hold prompt text (that is `trap_prompts`), gate or keep a draft (that is generation, through
`validity`), or keep state between runs.
"""

from collections.abc import Mapping
from typing import override

from bio_claim_check.engine.agent.base_llm_agent import BaseLlmAgent
from bio_claim_check.features.traps.models import TrapDraft, TrapPayload
from bio_claim_check.features.traps.trap_prompts import TRAP_PROMPT, trap_variables


class TrapLlmAgent(BaseLlmAgent[TrapPayload, TrapDraft]):
    name = "trap_writer"
    prompt = TRAP_PROMPT
    output = TrapDraft

    @override
    def variables(self, payload: TrapPayload) -> Mapping[str, str]:
        return trap_variables(payload)
