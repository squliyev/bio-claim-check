"""[TEST SUPPORT] Record real Foundry exchanges and scrub them into committable fixtures (I56).

`RecordingTransport` wraps a real `httpx2` transport and keeps each request path and JSON body and each
response status, headers and JSON body. `scrub` then removes everything that identifies the account or
the call: the host never enters an exchange (paths only), response headers shrink to the retry and
content-type ones, ids become `<prefix>_000…` of the same length, timestamps become 0, and the result is
refused if any given secret (the real host, the key) still appears anywhere in it.
"""

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast, override

import httpx2

from bio_claim_check.engine.llm.messages import LlmRequest, LlmResponse
from tests.support.llm_fixtures import SCRUBBED_HOST

KEPT_HEADERS = frozenset({"content-type", "retry-after", "retry-after-ms"})
_ID_PREFIX = re.compile(r"^([a-z]+)_")
_URL_HOST = re.compile(r"https?://([^/\"\s]+)")


class ScrubError(AssertionError):
    """A recording still contains something that must never be committed."""


class RecordingTransport(httpx2.BaseTransport):
    def __init__(self, inner: httpx2.BaseTransport) -> None:
        self._inner = inner
        self.exchanges: list[dict[str, Any]] = []

    @override
    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        response = self._inner.handle_request(request)
        response.read()
        self.exchanges.append(
            {
                "request": {"path": request.url.path, "body": json.loads(request.content)},
                "response": {
                    "status": response.status_code,
                    "headers": dict(response.headers),
                    "body": json.loads(response.content) if response.content else None,
                },
            }
        )
        return response

    @override
    def close(self) -> None:
        self._inner.close()


def _scrub_id(value: str) -> str:
    match = _ID_PREFIX.match(value)
    prefix = match.group(1) if match else "id"
    return f"{prefix}_{'0' * max(len(value) - len(prefix) - 1, 1)}"


def _scrub_value(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: _scrub_value(v, k) for k, v in cast(dict[str, Any], value).items()}
    if isinstance(value, list):
        return [_scrub_value(v, key) for v in cast(list[Any], value)]
    if key == "id" and isinstance(value, str):
        return _scrub_id(value)
    if key.endswith("_at") and isinstance(value, int | float) and not isinstance(value, bool):
        return 0
    return value


def scrub(exchanges: Iterable[dict[str, Any]], *, secrets: Iterable[str]) -> list[dict[str, Any]]:
    """Scrubbed copies of `exchanges`; raises `ScrubError` if a secret or a real host survives."""
    cleaned = [
        {
            "request": {"path": e["request"]["path"], "body": e["request"]["body"]},
            "response": {
                "status": e["response"]["status"],
                "headers": {
                    k.lower(): v for k, v in e["response"]["headers"].items() if k.lower() in KEPT_HEADERS
                },
                "body": _scrub_value(e["response"]["body"]),
            },
        }
        for e in exchanges
    ]
    text = json.dumps(cleaned)
    for secret in secrets:
        if secret and secret in text:
            raise ScrubError("a secret survived scrubbing")
    if hosts := set(_URL_HOST.findall(text)) - {SCRUBBED_HOST}:
        raise ScrubError(f"{len(hosts)} unscrubbed host(s) in a recording")
    return cleaned


def write_fixture(
    path: Path,
    *,
    note: str,
    request: LlmRequest,
    exchanges: list[dict[str, Any]],
    response: LlmResponse | None,
    error: str | None,
) -> None:
    """Write a `recorded` fixture in the shared format; `expected` is what the codec decoded live."""
    expected: dict[str, Any] = (
        {"response": response.model_dump(mode="json")} if response is not None else {"error": error}
    )
    fixture = {
        "provenance": "recorded",
        "note": note,
        "llm_request": request.model_dump(mode="json"),
        "exchanges": exchanges,
        "expected": expected,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(fixture, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
