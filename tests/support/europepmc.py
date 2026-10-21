"""[TEST SUPPORT] Fictional Europe PMC responses, served through `httpx.MockTransport` (never the network).

The fixtures in tests/fixtures/europepmc/ are hand-written in the shape the live API returned on
2026-10-20 (`resultType=core`). Every record is fictional: PMIDs are 9xxxxxxx (not yet allocated) and
DOIs use Crossref's 10.5555 test prefix. No publisher text is committed.
"""

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from bio_claim_check.engine.cache.base_cache import BaseCache
from bio_claim_check.engine.cache.in_memory_cache import InMemoryCache
from bio_claim_check.engine.cache.policy import CacheMode
from bio_claim_check.features.retrieval.europe_pmc_literature_source import EuropePmcLiteratureSource
from tests.support.paths import ROOT

FIXTURES = ROOT / "tests" / "fixtures" / "europepmc"

type Reply = httpx.Response | Exception | Callable[[httpx.Request], httpx.Response]


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def mixed_records() -> list[dict[str, Any]]:
    return copy.deepcopy(fixture("search_mixed.json")["resultList"]["result"])


def good_record() -> dict[str, Any]:
    """A citable record with every optional field present."""
    return mixed_records()[0]


def envelope(records: list[dict[str, Any]], *, hit_count: int | None = None) -> bytes:
    body = fixture("search_empty.json")
    body["hitCount"] = len(records) if hit_count is None else hit_count
    body["resultList"]["result"] = records
    return json.dumps(body).encode()


def ok(body: bytes) -> httpx.Response:
    return httpx.Response(200, content=body, headers={"Content-Type": "application/json"})


@dataclass
class ScriptedServer:
    """Replies in order; a request beyond the script fails the test."""

    replies: list[Reply]
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert self.replies, f"unexpected request #{len(self.requests)}: {request.url}"
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, httpx.Response):
            return reply
        return reply(request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=self.transport())


@dataclass
class Harness:
    server: ScriptedServer
    source: EuropePmcLiteratureSource
    cache: BaseCache
    sleeps: list[float]


def harness(
    *replies: Reply, cache: BaseCache | None = None, mode: CacheMode = CacheMode.READ_WRITE
) -> Harness:
    server = ScriptedServer(list(replies))
    store = cache if cache is not None else InMemoryCache()
    sleeps: list[float] = []
    source = EuropePmcLiteratureSource(server.client(), store, mode, sleep=sleeps.append)
    return Harness(server, source, store, sleeps)
