"""[RING:engine/llm] The engine's LLM vocabulary, translated to the primitives events carry.

Why: the `[LEAF]` events package cannot import `engine.llm`, so the runner and the backends map a
`ModelIdentity` to an event `ModelRef` here, in one place, and the backends' retry event is built here.
Must not: put anything but identifiers into an event.

Pure values: makes no provider call. (It is LLM vocabulary, so it does not carry the
ADR 0003 deterministic marker.)
"""

from collections.abc import Callable
from datetime import datetime

from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.llm_events import LlmRetryScheduled
from bio_claim_check.engine.events.pipeline_event import ModelRef
from bio_claim_check.engine.llm.model_spec import ModelIdentity


def model_ref(identity: ModelIdentity) -> ModelRef:
    return ModelRef(
        provider=identity.provider.value,
        deployment=identity.deployment,
        model_version=identity.model_version,
    )


def retry_hook(
    emitter: EventEmitter | None, identity: ModelIdentity
) -> Callable[[int, int | None, float], None]:
    """The `on_retry` callback a backend hands to `with_retries`: one `LlmRetryScheduled` per retry."""

    def hook(transport_attempt: int, status: int | None, delay: float) -> None:
        if emitter is None:
            return

        def build(at: datetime) -> LlmRetryScheduled:
            return LlmRetryScheduled(
                at=at,
                model=model_ref(identity),
                transport_attempt=transport_attempt,
                status=status,
                delay_s=delay,
            )

        emitter.emit(build)

    return hook
