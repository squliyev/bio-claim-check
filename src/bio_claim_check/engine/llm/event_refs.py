"""[RING:engine/llm] The engine's LLM vocabulary, translated to the primitives events carry.

Why: the `[LEAF]` events package cannot import `engine.llm`, so the runner and the backends map a
`ModelIdentity` to an event `ModelRef` here, in one place.
Must not: put anything but identifiers into an event.

Pure values: makes no provider call. (It is LLM vocabulary, so it does not carry the
ADR 0003 deterministic marker.)
"""

from bio_claim_check.engine.events.pipeline_event import ModelRef
from bio_claim_check.engine.llm.model_spec import ModelIdentity


def model_ref(identity: ModelIdentity) -> ModelRef:
    return ModelRef(
        provider=identity.provider.value,
        deployment=identity.deployment,
        model_version=identity.model_version,
    )
