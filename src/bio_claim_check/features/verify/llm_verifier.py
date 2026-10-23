"""[RING:features/verify] `BaseVerifier` backed by the verifier agent, one isolated call per pair.

Why: the agent judges the label; code decides the evidence status and negation, through
`Verdict.finalise` against the cleaned abstract, exactly as for the scripted verifier. A failure that
belongs to this pair's output (invalid or truncated output, a filtered response or prompt: the runner
raises all of them as `LlmCallError`) becomes one counted `VerifierFailure`. Every other error (any
provider rejection whatever its status, transport, unexpected response, budget, cache, our own request
bug) propagates and stops the run, so a broken
provider or schema can never become a column of per-pair "scientific" failures (I70).
Must not: retry, repair or re-ask (the runner owns that), catch an error it cannot attribute to the pair,
or see anything beyond `VerifyPayload` (I69).
"""

from typing import Final, override

from bio_claim_check.engine.agent.base_llm_agent import BaseLlmAgent
from bio_claim_check.engine.llm.errors import LlmCallError, LlmFailureKind
from bio_claim_check.features.contracts.labels import FailureKind
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.rulepack import RulePack
from bio_claim_check.features.contracts.verdict import Claim, Verdict, VerifierFailure, VerifierOutput
from bio_claim_check.features.verify.base_verifier import BaseVerifier
from bio_claim_check.features.verify.verify_models import VerifyPayload

type VerifyAgent = BaseLlmAgent[VerifyPayload, VerifierOutput]

PAIR_FAILURE: Final = {
    LlmFailureKind.INVALID_OUTPUT: FailureKind.STRUCTURED_OUTPUT,
    LlmFailureKind.TRUNCATED: FailureKind.STRUCTURED_OUTPUT,
    LlmFailureKind.CONTENT_FILTERED: FailureKind.CONTENT_FILTERED,
}


class LlmVerifier(BaseVerifier):
    """Judges each pair with the verifier agent; `app` wires the agent."""

    def __init__(self, agent: VerifyAgent) -> None:
        self._agent = agent

    @override
    def verify(self, claim: Claim, paper: Paper, rules: RulePack) -> Verdict | VerifierFailure:
        payload = VerifyPayload(claim=claim.text, title=paper.title, abstract=paper.abstract, rules=rules)
        try:
            out = self._agent.run(payload).output
        except LlmCallError as error:
            kind = PAIR_FAILURE[error.kind]
            return VerifierFailure(claim_id=claim.id, source_id=paper.source_id, kind=kind)
        return Verdict.finalise(claim.id, paper.source_id, out, paper.abstract)
