"""[RING:engine/pipeline] One LLM invocation: the domain payload and the only request a provider sees.

Why: context isolation (the verifier sees one claim and its cited abstract, nothing else) is only
checkable if what the model sees is a separate value from what the caller knows. `payload` is the
domain input and is never sent as-is; `request` is exactly what reaches the client. Processors return a
new invocation (frozen), so the input a test holds is never changed behind its back.
Must not: hold provider state, or be mutated in place.

Pure values: makes no provider call. (It is LLM vocabulary, so it does not carry the
ADR 0003 deterministic marker.)
"""

from dataclasses import dataclass, field

from bio_claim_check.engine.llm.messages import LlmRequest, LlmResponse
from bio_claim_check.engine.llm.usage import Spend


@dataclass(frozen=True, slots=True)
class Invocation[P]:
    payload: P
    request: LlmRequest
    responses: tuple[LlmResponse, ...] = ()
    spend: Spend = field(default_factory=Spend)
