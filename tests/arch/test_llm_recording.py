"""I56: the recording scrubber removes what must never be committed, and its output is a valid fixture."""

import json
from pathlib import Path
from typing import Any

import httpx2
import pytest

from tests.support.llm import request, response
from tests.support.llm_fixtures import load_fixture, openai_sdk
from tests.support.llm_recording import KEPT_HEADERS, RecordingTransport, ScrubError, scrub, write_fixture

pytestmark = pytest.mark.arch

REAL_HOST = "my-real-resource.example.com"
CANARY = "not-a-real-credential"


def _exchange(body: Any, headers: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "request": {"path": "/openai/v1/responses", "body": {"model": "m"}},
        "response": {"status": 200, "headers": headers or {}, "body": body},
    }


def test_the_transport_records_path_body_status_headers_and_json() -> None:
    def handler(req: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"id": "resp_abc", "ok": True}, headers={"apim-request-id": "x"})

    transport = RecordingTransport(httpx2.MockTransport(handler))
    sdk = openai_sdk(transport)
    assert sdk.post("/responses", body={"model": "m"}, cast_to=object) == {"id": "resp_abc", "ok": True}
    (recorded,) = transport.exchanges
    assert recorded["request"] == {"path": "/openai/v1/responses", "body": {"model": "m"}}
    assert recorded["response"]["status"] == 200
    assert recorded["response"]["headers"]["apim-request-id"] == "x"
    transport.close()


def test_scrub_keeps_only_retry_and_content_headers() -> None:
    headers = {
        "Content-Type": "application/json",
        "Retry-After": "2",
        "x-ms-region": "r",
        "apim-request-id": "1",
    }
    (cleaned,) = scrub([_exchange({}, headers)], secrets=())
    assert cleaned["response"]["headers"] == {"content-type": "application/json", "retry-after": "2"}
    assert set(cleaned["response"]["headers"]) <= KEPT_HEADERS


def test_scrub_zeroes_ids_keeping_prefix_and_length_and_timestamps() -> None:
    body = {
        "id": "resp_a1B2",
        "created_at": 1767225600,
        "output": [{"id": "msg_xyz", "content": [{"id": "chatcmpl-77"}]}],
        "flag_at": True,
    }
    (cleaned,) = scrub([_exchange(body)], secrets=())
    out = cleaned["response"]["body"]
    assert out["id"] == "resp_0000"
    assert out["created_at"] == 0
    assert out["output"][0]["id"] == "msg_000"
    assert out["output"][0]["content"][0]["id"] == "id_00000000"  # same length as "chatcmpl-77"
    assert out["flag_at"] is True  # only numeric timestamps


@pytest.mark.parametrize(
    "body",
    [
        {"note": f"echoed {CANARY}"},
        {"url": f"https://{REAL_HOST}/openai"},
        {"url": "https://another.example.net/x"},
    ],
)
def test_scrub_refuses_a_surviving_secret_or_real_host(body: dict[str, str]) -> None:
    with pytest.raises(ScrubError) as raised:
        scrub([_exchange(body)], secrets=(REAL_HOST, CANARY))
    assert CANARY not in str(raised.value)
    assert REAL_HOST not in str(raised.value)


def test_a_written_fixture_loads_and_is_labelled_recorded(tmp_path: Path) -> None:
    path = tmp_path / "foundry_openai" / "case.json"
    exchanges = scrub([_exchange({"id": "resp_1"})], secrets=())
    write_fixture(path, note="n", request=request(), exchanges=exchanges, response=response(), error=None)
    fixture = load_fixture(path)
    assert (fixture.provenance, fixture.expected, fixture.expected_error) == ("recorded", response(), None)
    assert json.loads(path.read_text())["exchanges"] == exchanges
    write_fixture(
        path, note="n", request=request(), exchanges=exchanges, response=None, error="llm.transport"
    )
    assert load_fixture(path).expected_error == "llm.transport"
