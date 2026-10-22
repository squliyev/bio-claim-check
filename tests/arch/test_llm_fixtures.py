"""I56: LLM fixtures are scrubbed and labelled, and the codecs still send exactly the recorded bodies.

Also pins I54 on every fixture: Responses requests keep nothing at the provider and replay no
reasoning; Anthropic requests never enable thinking.
"""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from bio_claim_check.engine.llm import anthropic_messages_codec, openai_responses_codec
from tests.support.llm_fixtures import LLM_FIXTURES, PROVIDERS, SCRUBBED_HOST, fixture_paths, load_fixture

pytestmark = pytest.mark.arch

ALLOWED_RESPONSE_HEADERS = frozenset({"content-type", "retry-after", "retry-after-ms"})
SCRUBBED_ID = re.compile(r"^[a-z]+_0+$")
ENCODERS = {
    "foundry_openai": openai_responses_codec.encode_request,
    "foundry_anthropic": anthropic_messages_codec.encode_request,
}
PATHS = fixture_paths()


def _walk(value: Any, key: str = "$") -> Iterator[tuple[str, Any]]:
    yield key, value
    if isinstance(value, dict):
        for k, v in cast(dict[str, Any], value).items():
            yield from _walk(v, k)
    elif isinstance(value, list):
        for v in cast(list[Any], value):
            yield from _walk(v, key)


def test_fixture_directories_are_exactly_the_providers() -> None:
    assert sorted(p.name for p in LLM_FIXTURES.iterdir() if p.is_dir()) == sorted(PROVIDERS)
    for provider in PROVIDERS:
        assert fixture_paths(provider), f"{provider} has no fixtures"


@pytest.mark.parametrize("path", PATHS, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_a_fixture_is_labelled_and_scrubbed(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    fixture = load_fixture(path)
    assert fixture.provenance in {"recorded", "synthetic"}
    assert str(fixture.raw.get("note", "")).strip(), "say what the case shows (and why synthetic, if so)"
    hosts = set(re.findall(r"https?://([^/\"\s]+)", text))
    assert hosts <= {SCRUBBED_HOST}, f"unscrubbed host(s) {hosts}"
    assert not re.search(r"azure\.com|openai\.azure|services\.ai", text, re.IGNORECASE)
    for exchange in fixture.exchanges:
        assert {h.lower() for h in exchange.headers} <= ALLOWED_RESPONSE_HEADERS
        for key, value in _walk(exchange.response):
            if key == "id":
                assert isinstance(value, str), f"{path.name}: id is not a string"
                assert SCRUBBED_ID.match(value), f"{path.name}: unscrubbed id {value!r}"


@pytest.mark.parametrize("path", PATHS, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_the_codec_still_sends_the_recorded_body(path: Path) -> None:
    fixture = load_fixture(path)
    body = ENCODERS[fixture.provider](fixture.request)
    assert all(exchange.body == body for exchange in fixture.exchanges)
    assert body["model"] == fixture.request.model.deployment


@pytest.mark.parametrize("path", PATHS, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_reasoning_is_never_sent_or_kept(path: Path) -> None:
    fixture = load_fixture(path)
    for exchange in fixture.exchanges:
        if fixture.provider == "foundry_openai":
            assert exchange.body["store"] is False
            assert not {"previous_response_id", "include", "conversation"} & set(exchange.body)
            assert all("id" not in item for item in exchange.body["input"])
        else:
            assert "thinking" not in exchange.body
