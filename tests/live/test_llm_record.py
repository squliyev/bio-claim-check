"""Record the LLM fixtures from the real Foundry deployments (`make record-llm`; never in CI).

Every case uses the fixed, fictional ping prompt, so a recording carries no domain text. Each run
rewrites `tests/fixtures/llm/<provider>/<case>.json` as `recorded`; `expected` is what the codec decoded
live, so review the diff before committing. Synthetic cases (filters, throttling) are not touched: they
cannot be provoked honestly with fictional text. Skipped unless `--record-llm` is given.
"""

import logging
from collections.abc import Callable
from pathlib import Path

import anthropic
import httpx2
import openai
import pytest
from tests.support.llm_fixtures import LLM_FIXTURES, ProviderDir
from tests.support.llm_recording import RecordingTransport, scrub, write_fixture

from bio_claim_check.app.container import build_llm_clients
from bio_claim_check.app.models import model_catalog
from bio_claim_check.app.settings import Settings, load_settings
from bio_claim_check.common.errors import BccError
from bio_claim_check.common.models import ValidatedModel
from bio_claim_check.engine.agent.ping_llm_agent import PING_PROMPT, PingReply
from bio_claim_check.engine.llm.messages import FinishReason, LlmRequest, LlmResponse, Message, request_for
from bio_claim_check.engine.llm.model_spec import ModelSpec
from bio_claim_check.engine.pipeline.llm_runner import REPAIR_INSTRUCTION
from bio_claim_check.engine.prompts.prompt_template import render

pytestmark = pytest.mark.live
log = logging.getLogger(__name__)

DEPLOYMENTS: dict[ProviderDir, str] = {
    "foundry_openai": "gpt-6.1-sol",
    "foundry_anthropic": "claude-opus-4-8",
}
TRUNCATING_BUDGET: dict[ProviderDir, int] = {"foundry_openai": 16, "foundry_anthropic": 1}  # 16 = API minimum


def _ping(spec: ModelSpec, params: dict[str, int] | None = None) -> LlmRequest:
    request = request_for(spec, render(PING_PROMPT, {}), params=params, prompt=PING_PROMPT.ref())
    return request.with_schema(PingReply.__name__, PingReply.model_json_schema(mode="validation"))


class CountReply(ValidatedModel):
    """A deliberately long, fictional reply: the ping reply fits inside the Responses minimum budget."""

    numbers: str


COUNT_TO_200 = 'Write the numbers from 1 to 200 in words, separated by commas, in the field "numbers".'


def _truncated(provider: ProviderDir, spec: ModelSpec) -> LlmRequest:
    system, _ = render(PING_PROMPT, {})
    request = request_for(
        spec,
        (system, Message(role="user", content=COUNT_TO_200)),
        params={"max_output_tokens": TRUNCATING_BUDGET[provider]},
    )
    return request.with_schema(CountReply.__name__, CountReply.model_json_schema(mode="validation"))


def _repair_turn(spec: ModelSpec) -> LlmRequest:
    first = _ping(spec)
    fix = REPAIR_INSTRUCTION.format(problems="ok [bool_parsing]")
    turns = (Message(role="assistant", content='{"ok": "maybe"}'), Message(role="user", content=fix))
    return first.with_messages((*first.messages, *turns))


type Case = tuple[str, Callable[[ProviderDir, ModelSpec], LlmRequest]]
CASES: tuple[Case, ...] = (
    ("The ping request answered normally (structured output, usage).", lambda _, s: _ping(s)),
    (
        "A fictional long reply with a tiny output budget: the provider stops for length.",
        _truncated,
    ),
    (
        "A repair turn: the earlier reply and the runner's correction go back as plain messages, no ids.",
        lambda _, s: _repair_turn(s),
    ),
)
NAMES = ("ok", "truncated", "repair_turn")


@pytest.fixture
def settings(live_env_file: Path) -> Settings:
    loaded = load_settings(live_env_file if live_env_file.is_file() else None)
    if loaded.foundry is None:
        pytest.skip("no Foundry settings (BCC_FOUNDRY__BASE_URL / BCC_FOUNDRY__API_KEY in .env)")
    return loaded


@pytest.mark.parametrize("provider", list(DEPLOYMENTS))
@pytest.mark.parametrize("index", range(len(CASES)), ids=NAMES)
def test_record(record_llm: bool, settings: Settings, provider: ProviderDir, index: int) -> None:
    if not record_llm:
        pytest.skip("pass --record-llm (make record-llm) to rewrite the recorded fixtures")
    assert settings.foundry is not None
    note, build = CASES[index]
    spec = model_catalog().lookup(DEPLOYMENTS[provider])
    request = build(provider, spec)
    transport = RecordingTransport(httpx2.HTTPTransport())
    response: LlmResponse | None = None
    error: BccError | None = None
    with build_llm_clients(
        settings,
        [spec],
        openai_http=openai.DefaultHttpxClient(transport=transport),
        anthropic_http=anthropic.DefaultHttpxClient(transport=transport),
    ) as clients:
        try:
            response = clients[spec.deployment].complete(request)
        except BccError as caught:
            error = caught
    secrets = (settings.foundry.base_url.host or "", settings.foundry.api_key.get_secret_value())
    write_fixture(
        LLM_FIXTURES / provider / f"{NAMES[index]}.json",
        note=note,
        request=request,
        exchanges=scrub(transport.exchanges, secrets=secrets),
        response=response,
        error=None if error is None else error.code,
    )
    log.info("recorded %s/%s: %d exchange(s)", provider, NAMES[index], len(transport.exchanges))
    if error is not None:
        pytest.fail(f"{provider}/{NAMES[index]} failed live with {error.code}; fixture written, review it")
    if NAMES[index] == "truncated":
        assert response is not None
        assert response.finish_reason is FinishReason.LENGTH, "the truncated case must record a length stop"
