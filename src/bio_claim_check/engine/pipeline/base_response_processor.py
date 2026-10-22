"""[RING:engine/pipeline] The response-side extension point: act on validated, typed output.

Why: processors such as evidence location and negation (S10/S12) must only ever see output that has
already passed schema validation, so they receive the typed value, never raw text. Spend is recorded by
the runner before any processor runs, so a failing processor can never lose what a call cost.
Must not: call a provider, re-validate raw text, or mutate the invocation it receives.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel

from bio_claim_check.engine.pipeline.invocation import Invocation


class BaseResponseProcessor[P, T: BaseModel](ABC):
    """[EXTENSION POINT] Implemented in any features/engine package as `<what>_base_response_processor`.

    Runs after validation succeeds, in the order `app` gives the runner; returns a new invocation.
    """

    @abstractmethod
    def process(self, invocation: Invocation[P], output: T) -> Invocation[P]: ...
