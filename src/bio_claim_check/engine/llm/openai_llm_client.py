"""[RING:engine/llm] The Azure AI Foundry `/openai/v1` Responses-API backend: the only `openai` importer.

Why: S09 puts real provider calls behind `BaseLlmClient`. This module is a thin transport shell: the
request body and the response decoding are the pure `openai_responses_codec` (D1), the retry decisions
are the pure `transport_policy` (D11), and this class only posts the body and turns the SDK's
exceptions into neutral `TransportFailure`s. It posts through the SDK's generic `post` and decodes the
wire JSON itself, so the bytes the codec sees live are the bytes the recorded fixtures replay (I56).
The SDK's own retries must be off (`max_retries=0`, checked here), so `transport_policy` is the only
retry loop and every retry emits an `LlmRetryScheduled` event.
Must not: retry by itself, read configuration, or let a provider message or body reach an error, a log
or an event (the SDK's exception text embeds the body; it is dropped, never chained).
"""

from collections.abc import Callable, Mapping
from typing import cast, override

import httpx2
import openai
from pydantic import JsonValue

from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.llm.base_llm_client import BaseLlmClient
from bio_claim_check.engine.llm.codec_support import unexpected
from bio_claim_check.engine.llm.event_refs import retry_hook
from bio_claim_check.engine.llm.messages import LlmRequest, LlmResponse
from bio_claim_check.engine.llm.openai_responses_codec import decode_response, encode_request
from bio_claim_check.engine.llm.transport_policy import (
    TransportFailure,
    provider_error_code,
    retry_headers,
    with_retries,
)

type RawJson = Mapping[str, JsonValue]

PATH = "/responses"


class OpenAiLlmClient(BaseLlmClient):
    """Calls one Foundry resource's Responses API; the deployment name travels in each request body."""

    def __init__(
        self,
        sdk: openai.OpenAI,
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
        return decode_response(raw, deployment)

    def _post(
        self, body: Mapping[str, JsonValue], deployment: str
    ) -> Mapping[str, JsonValue] | TransportFailure:
        try:
            result = self._sdk.post(PATH, body=body, cast_to=object)
        except openai.APITimeoutError:
            return TransportFailure(status=None, maybe_billed=True)
        except openai.APIConnectionError as error:
            # Only a refused connection proves the request never left; a later drop may have been billed.
            refused = isinstance(error.__cause__, httpx2.ConnectError)
            return TransportFailure(status=None, maybe_billed=not refused)
        except openai.APIStatusError as error:
            return TransportFailure(
                status=error.status_code,
                headers=retry_headers(error.response.headers),
                provider_code=provider_error_code(error.body),
            )
        except ValueError:  # a 200 whose body is not JSON; the decoder error holds the body, so drop it
            raise unexpected(deployment, "$", "is not valid JSON") from None
        if not isinstance(result, dict):
            raise unexpected(deployment, "$", "is not a JSON object")
        return cast(dict[str, JsonValue], result)
