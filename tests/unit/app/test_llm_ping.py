"""`llm ping` (S09): the use case on scripted clients, and the CLI through the real container and SDKs."""

import contextlib
import json
from collections.abc import Generator, Iterable
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import openai
import pytest
from tests.support.llm import response, spec
from tests.support.llm_fixtures import LLM_FIXTURES, load_fixture
from typer.testing import CliRunner

from bio_claim_check.app import cli
from bio_claim_check.app.container import build_llm_clients
from bio_claim_check.app.models import model_catalog
from bio_claim_check.app.settings import Settings
from bio_claim_check.app.usecases.llm_ping import ping
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.llm.base_llm_client import BaseLlmClient
from bio_claim_check.engine.llm.errors import LlmTransportError
from bio_claim_check.engine.llm.messages import FinishReason
from bio_claim_check.engine.llm.model_spec import ModelSpec
from bio_claim_check.engine.llm.scripted_llm_client import ScriptedLlmClient
from bio_claim_check.engine.llm.usage import Usage

pytestmark = pytest.mark.unit
runner = CliRunner()


def test_each_deployment_is_pinged_and_a_failure_does_not_stop_the_rest() -> None:
    a, b = spec("model-a"), spec("model-b")
    clients: dict[str, BaseLlmClient] = {
        "model-a": ScriptedLlmClient(
            [LlmTransportError(deployment="model-a", status=503, attempts=4, reason="unavailable")]
        ),
        "model-b": ScriptedLlmClient(
            [response('{"ok": true}', usage=Usage(input_tokens=5, output_tokens=2))]
        ),
    }
    first, second = ping(clients, [a, b])
    assert (first.ok, first.error_code, first.deployment, first.model_version) == (
        False,
        "llm.transport",
        "model-a",
        "model-a-v1",
    )
    assert second.ok
    assert (second.finish, second.attempts) == (FinishReason.STOP, 1)
    assert second.usage == Usage(input_tokens=5, output_tokens=2)


def test_a_reply_that_never_validates_is_a_failed_ping_after_one_repair() -> None:
    client = ScriptedLlmClient([response("nope"), response('{"ok": "maybe"}')])
    (result,) = ping({"model-a": client}, [spec()])
    assert result.error_code == "llm.call_failed"
    assert len(client.requests) == 2


# ---------------------------------------------------------------- CLI


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BCC_CONTACT_EMAIL", "someone@example.org")
    monkeypatch.setenv("BCC_FOUNDRY__BASE_URL", "https://foundry.example.invalid")
    monkeypatch.setenv("BCC_FOUNDRY__API_KEY", "test-key-not-a-secret")


def _ok_body(provider: str) -> dict[str, Any]:
    fixture = json.loads((LLM_FIXTURES / provider / "ok.json").read_text())
    return fixture["exchanges"][0]["response"]["body"]


def serve(monkeypatch: pytest.MonkeyPatch, status: int = 200) -> list[str]:
    """The real container and SDKs over a mock transport that answers like Foundry."""
    paths: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.path)
        if status != 200:
            return httpx2.Response(status, json={"error": {"code": "Unauthorized"}})
        provider = "foundry_openai" if request.url.path.endswith("/responses") else "foundry_anthropic"
        return httpx2.Response(200, json=_ok_body(provider))

    @contextlib.contextmanager
    def mocked(
        settings: Settings, specs: Iterable[ModelSpec], **kwargs: Any
    ) -> Generator[dict[str, BaseLlmClient]]:
        with build_llm_clients(
            settings,
            specs,
            sleep=lambda _: None,
            openai_http=openai.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
            anthropic_http=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
            **kwargs,
        ) as clients:
            yield clients

    monkeypatch.setattr(cli, "build_llm_clients", mocked)
    monkeypatch.setattr(cli, "logging_emitter", lambda: None)
    return paths


def llm_ping(*args: str) -> tuple[int, str, str]:
    result = runner.invoke(cli.app, ["llm", "ping", *args, "--env-file", str(Path("/nonexistent/.env"))])
    return result.exit_code, result.stdout, result.stderr


def test_default_pings_the_answer_and_verifier_deployments(
    env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = serve(monkeypatch)
    code, out, err = llm_ping()
    assert code == 0, err
    assert paths == ["/openai/v1/responses", "/anthropic/v1/messages"]
    lines = out.splitlines()
    assert lines[0].startswith(
        "ok   gpt-6.1-sol (pinned 2026-09-29): served=gpt-6.1-sol finish=stop attempts=1"
    )
    for line, provider in zip(lines, ("foundry_openai", "foundry_anthropic"), strict=True):
        expected = load_fixture(LLM_FIXTURES / provider / "ok.json").expected
        assert expected is not None
        u = expected.usage
        assert line.endswith(
            f"in={u.input_tokens} out={u.output_tokens} reasoning={u.reasoning_tokens} "
            f"cached={u.cached_input_tokens}"
        )
    assert lines[1].startswith("ok   claude-opus-4-8 (pinned claude-opus-4-8)")


def test_a_provider_failure_exits_provider_and_names_the_code(
    env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(monkeypatch, status=401)
    code, out, _ = llm_ping("gpt-6.1-sol")
    assert code == cli.ExitCode.PROVIDER
    assert out == "FAIL gpt-6.1-sol (pinned 2026-09-29): llm.provider_rejected\n"
    assert "test-key" not in out


@pytest.mark.parametrize(
    ("args", "needs_foundry", "message"),
    [
        (["gpt-typo"], True, "gpt-typo"),
        (["gpt-6.1-sol"], False, "foundry settings"),
    ],
)
def test_bad_input_exits_input_before_any_call(
    monkeypatch: pytest.MonkeyPatch, args: list[str], needs_foundry: bool, message: str
) -> None:
    monkeypatch.setenv("BCC_CONTACT_EMAIL", "someone@example.org")
    if needs_foundry:
        monkeypatch.setenv("BCC_FOUNDRY__BASE_URL", "https://foundry.example.invalid")
        monkeypatch.setenv("BCC_FOUNDRY__API_KEY", "test-key-not-a-secret")
    paths = serve(monkeypatch)
    code, _, err = llm_ping(*args)
    assert code == cli.ExitCode.INPUT
    assert message in err
    assert paths == []


def test_the_catalogue_deployments_resolve() -> None:
    assert model_catalog().lookup("gpt-6.1-sol").model_version == "2026-09-29"


def test_logging_emitter_is_the_cli_default() -> None:
    assert isinstance(cli.logging_emitter(), EventEmitter)
