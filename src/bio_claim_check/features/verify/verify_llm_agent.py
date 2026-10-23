"""[RING:features/verify] The verifier agent: judges one claim against one cited abstract.

Why: the LLM half of verification. It declares its prompt and output and writes its variables; the
agent base owns rendering, the request and the runner (ADR 0015). Its output is the S05 `VerifierOutput`
(flat, every field required, so strict structured output accepts it).
Must not: hold prompt text (that is `verify_prompts`), build a `Verdict` (that is `LlmVerifier`, through
`Verdict.finalise`), or keep state between runs.
"""

from collections.abc import Mapping
from typing import override

from bio_claim_check.engine.agent.base_llm_agent import BaseLlmAgent
from bio_claim_check.features.contracts.verdict import VerifierOutput
from bio_claim_check.features.verify.verify_models import VerifyPayload
from bio_claim_check.features.verify.verify_prompts import VERIFY_PROMPT, verify_variables


class VerifyLlmAgent(BaseLlmAgent[VerifyPayload, VerifierOutput]):
    name = "verifier"
    prompt = VERIFY_PROMPT
    output = VerifierOutput

    @override
    def variables(self, payload: VerifyPayload) -> Mapping[str, str]:
        return verify_variables(payload)
