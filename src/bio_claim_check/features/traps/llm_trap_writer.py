"""[RING:features/traps] `BaseTrapWriter` backed by the trap writer agent, one isolated call per source.

Why: a failure that belongs to this source's output (invalid or truncated output, a filtered response
or prompt) becomes one counted `TrapWriterFailure`, so attrition is reported, not hidden. Every other
error (provider rejection, transport, unexpected response, budget, cache) propagates and stops the run,
exactly as for the verifier (I70), so a broken provider never becomes a column of "failed drafts".
Must not: retry, repair or re-ask (the runner owns that), or see anything beyond `TrapPayload`.
"""

from typing import Final, override

from bio_claim_check.engine.agent.base_llm_agent import BaseLlmAgent
from bio_claim_check.engine.llm.errors import LlmCallError, LlmFailureKind
from bio_claim_check.features.contracts.labels import FailureKind, OverstatedReason
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.rulepack import Rule
from bio_claim_check.features.traps.base_trap_writer import BaseTrapWriter
from bio_claim_check.features.traps.models import TrapDraft, TrapPayload, TrapWriterFailure

type TrapAgent = BaseLlmAgent[TrapPayload, TrapDraft]

SOURCE_FAILURE: Final = {
    LlmFailureKind.INVALID_OUTPUT: FailureKind.STRUCTURED_OUTPUT,
    LlmFailureKind.TRUNCATED: FailureKind.STRUCTURED_OUTPUT,
    LlmFailureKind.CONTENT_FILTERED: FailureKind.CONTENT_FILTERED,
}
"""The verifier's pair-failure mapping, repeated because slices never import each other (a test pins it)."""


class LlmTrapWriter(BaseTrapWriter):
    """Drafts each source with the trap writer agent; `app` wires the agent."""

    def __init__(self, agent: TrapAgent) -> None:
        self._agent = agent

    @override
    def draft(self, kind: OverstatedReason, rule: Rule, paper: Paper) -> TrapDraft | TrapWriterFailure:
        payload = TrapPayload(
            reason=kind.value, definition=rule.definition, title=paper.title, abstract=paper.abstract
        )
        try:
            return self._agent.run(payload).output
        except LlmCallError as error:
            return TrapWriterFailure(source_id=paper.source_id, kind=SOURCE_FAILURE[error.kind])
