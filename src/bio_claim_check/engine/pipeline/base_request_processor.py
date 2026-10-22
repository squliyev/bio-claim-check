"""[RING:engine/pipeline] The request-side extension point: shape what the model will see.

Why: behaviour such as context isolation (S12) lives in the slice that understands it, as a small
processor, instead of growing one large function. The runner applies processors in the order `app`
gives it, once, before the first attempt.
Must not: call a provider, read the clock, or mutate the invocation it receives.
"""

from abc import ABC, abstractmethod

from bio_claim_check.engine.pipeline.invocation import Invocation


class BaseRequestProcessor[P](ABC):
    """[EXTENSION POINT] Implemented in any features/engine package as `<what>_base_request_processor`.

    Returns a new invocation; a processor that raises has found a bug, and the error propagates.
    """

    @abstractmethod
    def process(self, invocation: Invocation[P]) -> Invocation[P]: ...
