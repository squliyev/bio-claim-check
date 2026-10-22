"""[TEST SUPPORT] LLM provider fixtures: load, replay through `httpx2.MockTransport`, build backends.

A fixture in tests/fixtures/llm/<provider>/<case>.json is one `complete()` call:
`provenance` (`recorded`: a scrubbed live exchange; `synthetic`: hand-built from the documented shape,
for cases that cannot be provoked honestly with fictional text), the `llm_request` we sent, the ordered
HTTP `exchanges` (several when the backend retried), and the `expected` normalised response or error
code. Replay asserts that each wire request still equals the recorded body (the drift test, I56), so a
codec change that alters what we send fails here before it reaches a provider. Never the network.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import anthropic
import httpx2
import openai

from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.llm.anthropic_llm_client import AnthropicLlmClient
from bio_claim_check.engine.llm.base_llm_client import BaseLlmClient
from bio_claim_check.engine.llm.messages import LlmRequest, LlmResponse
from bio_claim_check.engine.llm.openai_llm_client import OpenAiLlmClient
from tests.support.paths import ROOT

LLM_FIXTURES = ROOT / "tests" / "fixtures" / "llm"
SCRUBBED_HOST = "foundry.example.invalid"
BASE_URL = f"https://{SCRUBBED_HOST}"
API_KEY = "test-key-not-a-secret"
type ProviderDir = Literal["foundry_openai", "foundry_anthropic"]
PROVIDERS: tuple[ProviderDir, ...] = ("foundry_openai", "foundry_anthropic")


@dataclass(frozen=True)
class Exchange:
    path: str
    body: dict[str, Any]
    status: int
    headers: dict[str, str]
    response: Any


@dataclass(frozen=True)
class LlmFixture:
    name: str
    provider: ProviderDir
    provenance: Literal["recorded", "synthetic"]
    request: LlmRequest
    exchanges: tuple[Exchange, ...]
    expected: LlmResponse | None
    expected_error: str | None
    raw: dict[str, Any] = field(repr=False)


def fixture_paths(provider: ProviderDir | None = None) -> list[Path]:
    providers = PROVIDERS if provider is None else (provider,)
    return sorted(p for name in providers for p in (LLM_FIXTURES / name).glob("*.json"))


def load_fixture(path: Path) -> LlmFixture:
    raw = json.loads(path.read_text(encoding="utf-8"))
    expected = raw["expected"]
    return LlmFixture(
        name=f"{path.parent.name}/{path.stem}",
        provider=cast(ProviderDir, path.parent.name),
        provenance=raw["provenance"],
        request=LlmRequest.model_validate(raw["llm_request"]),
        exchanges=tuple(
            Exchange(
                path=e["request"]["path"],
                body=e["request"]["body"],
                status=e["response"]["status"],
                headers=e["response"].get("headers", {}),
                response=e["response"]["body"],
            )
            for e in raw["exchanges"]
        ),
        expected=LlmResponse.model_validate(expected["response"]) if "response" in expected else None,
        expected_error=expected.get("error"),
        raw=raw,
    )


def load_fixtures(provider: ProviderDir | None = None, *, success_only: bool = False) -> list[LlmFixture]:
    fixtures = [load_fixture(p) for p in fixture_paths(provider)]
    return [f for f in fixtures if f.expected is not None] if success_only else fixtures


class ReplayTransport(httpx2.MockTransport):
    """Serves `exchanges` in order; a request that differs from the recorded one fails the test."""

    def __init__(self, exchanges: tuple[Exchange, ...]) -> None:
        self.pending = list(exchanges)
        self.seen: list[httpx2.Request] = []
        super().__init__(self._serve)

    def _serve(self, request: httpx2.Request) -> httpx2.Response:
        self.seen.append(request)
        assert self.pending, f"unexpected extra request to {request.url.path}"
        exchange = self.pending.pop(0)
        assert request.url.host == SCRUBBED_HOST
        assert request.url.path == exchange.path
        assert json.loads(request.content) == exchange.body, "the codec no longer sends the recorded body"
        return httpx2.Response(exchange.status, json=exchange.response, headers=exchange.headers)


type Handler = Callable[[httpx2.Request], httpx2.Response]


def openai_sdk(transport: httpx2.BaseTransport, *, max_retries: int = 0) -> openai.OpenAI:
    return openai.OpenAI(
        base_url=f"{BASE_URL}/openai/v1/",
        api_key=API_KEY,
        max_retries=max_retries,
        http_client=httpx2.Client(transport=transport),
    )


def anthropic_sdk(transport: httpx2.BaseTransport, *, max_retries: int = 0) -> anthropic.AnthropicFoundry:
    return anthropic.AnthropicFoundry(
        base_url=f"{BASE_URL}/anthropic",
        api_key=API_KEY,
        max_retries=max_retries,
        http_client=httpx2.Client(transport=transport),
    )


def backend(
    provider: ProviderDir,
    transport: httpx2.BaseTransport,
    *,
    sleeps: list[float] | None = None,
    emitter: EventEmitter | None = None,
) -> BaseLlmClient:
    sleep = (sleeps if sleeps is not None else []).append
    if provider == "foundry_openai":
        return OpenAiLlmClient(openai_sdk(transport), sleep=sleep, emitter=emitter)
    return AnthropicLlmClient(anthropic_sdk(transport), sleep=sleep, emitter=emitter)


def replay(
    fixture: LlmFixture, *, sleeps: list[float] | None = None
) -> tuple[BaseLlmClient, ReplayTransport]:
    transport = ReplayTransport(fixture.exchanges)
    return backend(fixture.provider, transport, sleeps=sleeps), transport
