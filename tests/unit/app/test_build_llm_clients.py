"""LLM wiring (S09): URLs derive from one Foundry resource, SDK retries are off, unknown providers fail.

The tests read the backends' `_sdk` through `Any` on purpose: the wiring itself is under test.
"""

import json
from typing import Any

import anthropic
import httpx2
import openai
import pytest
from tests.support.llm_fixtures import PROVIDERS, fixture_paths, load_fixture
from tests.support.settings import make_settings

from bio_claim_check.app.container import (
    LLM_CONNECT_TIMEOUT_S,
    LLM_TIMEOUT_S,
    MissingProviderError,
    UnsupportedProviderError,
    build_llm_clients,
    foundry_urls,
)
from bio_claim_check.app.models import model_catalog
from bio_claim_check.engine.llm.anthropic_llm_client import AnthropicLlmClient
from bio_claim_check.engine.llm.errors import LlmProviderError
from bio_claim_check.engine.llm.model_spec import ModelSpec, Provider
from bio_claim_check.engine.llm.openai_llm_client import OpenAiLlmClient

pytestmark = pytest.mark.unit

FOUNDRY = {"base_url": "https://foundry.example.invalid/", "api_key": "test-key"}
GPT = model_catalog().lookup("gpt-6.1-sol")
CLAUDE = model_catalog().lookup("claude-opus-4-8")


def test_foundry_urls_derive_both_apis_from_one_resource() -> None:
    assert foundry_urls("https://foundry.example.invalid/") == (
        "https://foundry.example.invalid/openai/v1/",
        "https://foundry.example.invalid/anthropic",
    )
    assert foundry_urls("https://foundry.example.invalid") == foundry_urls("https://foundry.example.invalid/")


def test_each_deployment_gets_its_provider_backend_and_one_sdk_per_api() -> None:
    other = ModelSpec(
        deployment="gpt-other", provider=Provider.FOUNDRY_OPENAI, model_version="v1", price=None
    )
    with build_llm_clients(make_settings(foundry=FOUNDRY), [GPT, CLAUDE, other]) as clients:
        assert set(clients) == {"gpt-6.1-sol", "claude-opus-4-8", "gpt-other"}
        assert isinstance(clients["gpt-6.1-sol"], OpenAiLlmClient)
        assert isinstance(clients["claude-opus-4-8"], AnthropicLlmClient)
        assert clients["gpt-other"] is clients["gpt-6.1-sol"]


def test_sdks_have_retries_off_our_timeouts_and_the_derived_urls() -> None:
    with build_llm_clients(make_settings(foundry=FOUNDRY), [GPT, CLAUDE]) as clients:
        gpt: Any = clients["gpt-6.1-sol"]
        claude: Any = clients["claude-opus-4-8"]
        gpt_sdk: openai.OpenAI = gpt._sdk
        claude_sdk: anthropic.AnthropicFoundry = claude._sdk
    assert str(gpt_sdk.base_url) == "https://foundry.example.invalid/openai/v1/"
    assert str(claude_sdk.base_url).rstrip("/") == "https://foundry.example.invalid/anthropic"
    for sdk in (gpt_sdk, claude_sdk):
        assert sdk.max_retries == 0
        timeout: Any = sdk.timeout
        assert (timeout.read, timeout.connect) == (LLM_TIMEOUT_S, LLM_CONNECT_TIMEOUT_S)


def test_the_sdk_clients_are_closed_on_exit() -> None:
    with build_llm_clients(make_settings(foundry=FOUNDRY), [GPT, CLAUDE]) as clients:
        gpt: Any = clients["gpt-6.1-sol"]
        claude: Any = clients["claude-opus-4-8"]
    assert gpt._sdk.is_closed()
    assert claude._sdk.is_closed()


def test_requests_go_to_the_derived_paths_with_the_key() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(401, json={"error": {"code": "unauthorized"}})

    with build_llm_clients(
        make_settings(foundry=FOUNDRY),
        [GPT, CLAUDE],
        openai_http=openai.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
        anthropic_http=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    ) as clients:
        for fixture in (load_fixture(fixture_paths(p)[0]) for p in PROVIDERS):
            with pytest.raises(LlmProviderError) as raised:
                clients[fixture.request.model.deployment].complete(fixture.request)
            assert raised.value.status == 401
    assert [r.url.path for r in seen] == ["/openai/v1/responses", "/anthropic/v1/messages"]
    assert seen[0].headers["authorization"] == "Bearer test-key"
    assert seen[1].headers["api-key"] == "test-key"
    assert [json.loads(r.content)["model"] for r in seen] == ["gpt-6.1-sol", "claude-opus-4-8"]


def test_missing_foundry_settings_fail_before_any_client() -> None:
    with (
        pytest.raises(MissingProviderError, match=r"gpt-6\.1-sol"),
        build_llm_clients(make_settings(), [GPT]),
    ):
        pass


@pytest.mark.parametrize("provider", [Provider.ANTHROPIC, Provider.OLLAMA])
def test_a_provider_without_an_adapter_is_refused_by_name(provider: Provider) -> None:
    spec = ModelSpec(deployment="some-model", provider=provider, model_version="v1", price=None)
    with (
        pytest.raises(UnsupportedProviderError, match="some-model"),
        build_llm_clients(make_settings(foundry=FOUNDRY), [GPT, spec]),
    ):
        pass


def test_no_specs_build_nothing_and_need_no_settings() -> None:
    with build_llm_clients(make_settings(), []) as clients:
        assert clients == {}


def test_pinned_versions_and_the_claude_budget() -> None:
    assert GPT.model_version == "2026-09-29"
    assert CLAUDE.params == {"max_output_tokens": 8192}
