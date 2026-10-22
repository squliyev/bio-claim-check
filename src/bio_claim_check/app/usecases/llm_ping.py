"""[RING:app/usecases] `llm ping`: one tiny structured call per deployment through `PingLlmAgent`.

Why: S09's live exit check. It proves, before any real question is spent, that each deployment answers
through the same agent base, runner and backend the pipeline will use: endpoint, key, pinned version,
structured output and usage reporting. It bypasses the cache on purpose (the caller passes live clients),
so a ping always reaches the provider.
Must not: build clients or read settings (the CLI wires them through the container), send domain text,
or swallow a failure: each deployment's typed error code is reported and fails the command.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from bio_claim_check.common.errors import BccError
from bio_claim_check.engine.agent.ping_llm_agent import PingLlmAgent
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.llm.base_llm_client import BaseLlmClient
from bio_claim_check.engine.llm.messages import FinishReason
from bio_claim_check.engine.llm.model_spec import ModelSpec
from bio_claim_check.engine.llm.usage import Usage


@dataclass(frozen=True, slots=True)
class PingResult:
    """One deployment's ping: what was pinned, what served it, and how it went."""

    deployment: str
    model_version: str
    served_model: str | None = None
    finish: FinishReason | None = None
    usage: Usage | None = None
    attempts: int = 0
    error_code: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_code is None


def ping(
    clients: Mapping[str, BaseLlmClient],
    specs: Sequence[ModelSpec],
    *,
    emitter: EventEmitter | None = None,
) -> list[PingResult]:
    """Ping each spec in order; a failure is recorded with its code and the next deployment still runs."""
    results: list[PingResult] = []
    for spec in specs:
        agent = PingLlmAgent(clients[spec.deployment], spec, emitter=emitter)
        try:
            result = agent.run(None)
        except BccError as error:
            results.append(PingResult(spec.deployment, spec.model_version, error_code=error.code))
            continue
        last = result.invocation.responses[-1]
        results.append(
            PingResult(
                deployment=spec.deployment,
                model_version=spec.model_version,
                served_model=last.served_model,
                finish=last.finish_reason,
                usage=result.invocation.spend.usage,
                attempts=len(result.invocation.responses),
            )
        )
    return results
