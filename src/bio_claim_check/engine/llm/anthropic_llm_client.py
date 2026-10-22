"""[RING:engine/llm] The Azure AI Foundry Anthropic Messages-API backend: the only `anthropic` importer.

Why: the twin of `openai_llm_client` for Claude deployments, served by `AnthropicFoundry` from the
same Foundry resource and key (`<resource>/anthropic`). The request body and the decoding are the pure
`anthropic_messages_codec` (forced tool use, no thinking; D6, D7), the retry decisions are the pure
`transport_policy` (D11), and this class only posts and maps the SDK's exceptions to neutral
`TransportFailure`s. It posts through the SDK's generic `post` and decodes the wire JSON, so live calls
and recorded fixtures go through the same bytes (I56). SDK retries must be off (`max_retries=0`).
Must not: retry by itself, read configuration, enable thinking, or let a provider message or body
reach an error, a log or an event (the SDK's exception text embeds the body; it is dropped).
"""

from collections.abc import Callable, Mapping
from typing import cast, override

import anthropic
from pydantic import JsonValue

from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.llm.anthropic_messages_codec import decode_response, encode_request, forced_tool
from bio_claim_check.engine.llm.base_llm_client import BaseLlmClient
from bio_claim_check.engine.llm.codec_support import unexpected
from bio_claim_check.engine.llm.event_refs import retry_hook
from bio_claim_check.engine.llm.messages import LlmRequest, LlmResponse
from bio_claim_check.engine.llm.transport_policy import (
    TransportFailure,
    provider_error_code,
    retry_headers,
    with_retries,
)

type RawJson = Mapping[str, JsonValue]

PATH = "/v1/messages"


class AnthropicLlmClient(BaseLlmClient):
    """Calls one Foundry resource's Anthropic Messages API; the deployment name travels in each body."""

    def __init__(
        self,
        sdk: anthropic.AnthropicFoundry,
        *,
        sleep: Callable[[float], None],
        emitter: EventEmitter | None = None,
    ) -> None:
        if sdk.max_retries != 0:
            raise ValueError("the SDK must be built with max_retries=0: transport_policy owns retries (I55)")
        self._sdk = sdk
        self._sleep = sleep
        self._emitter = emitter

    @override
    def complete(self, request: LlmRequest) -> LlmResponse:
        body = encode_request(request)
        deployment = request.model.deployment
        raw = with_retries(
            lambda: self._post(body, deployment),
            deployment=deployment,
            sleep=self._sleep,
            on_retry=retry_hook(self._emitter, request.model),
        )
        return decode_response(raw, deployment, tool=forced_tool(request))

    def _post(
        self, body: Mapping[str, JsonValue], deployment: str
    ) -> Mapping[str, JsonValue] | TransportFailure:
        try:
            result = self._sdk.post(PATH, body=body, cast_to=object)
        except anthropic.APITimeoutError:
            return TransportFailure(status=None, timed_out=True)
        except anthropic.APIConnectionError:
            return TransportFailure(status=None)
        except anthropic.APIStatusError as error:
            return TransportFailure(
                status=error.status_code,
                headers=retry_headers(error.response.headers),
                provider_code=provider_error_code(error.body),
            )
        if not isinstance(result, dict):
            raise unexpected(deployment, "$", "is not a JSON object")
        return cast(dict[str, JsonValue], result)
