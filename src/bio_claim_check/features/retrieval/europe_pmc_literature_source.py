"""[RING:features/retrieval] Europe PMC backend: real MEDLINE/PubMed-indexed abstracts over the REST API.

Why: the claim checker needs real, citable abstracts. Europe PMC's REST service is the sanctioned route
for automated access (its terms forbid crawling the website; ADR 0008). Every response goes through the
content-addressed cache (ADR 0009), so a second identical run, CI and replays make no network call.
Only a fully validated 200 response is stored: a status error or a malformed body raises inside the
fetch, before the cache is written.
Retries are deterministic (1, 2, 4 s, or `Retry-After` capped at 60 s): no randomness, and the sleep is
injected, so tests take no time. Requests are sequential; one search is one request.
Must not: log request headers (they carry the contact email), rewrite the query, page beyond one request,
or construct its own HTTP client (the app builds it with the User-Agent and timeouts).

No LLM is involved in this module.
"""

import json
import logging
import time
from collections import Counter
from collections.abc import Callable, Mapping
from typing import cast, override

import httpx
from pydantic import JsonValue

from bio_claim_check.engine.cache.base_cache import BaseCache
from bio_claim_check.engine.cache.policy import CacheMode, cache_key, fetch_through
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.retrieval.citable import (
    MalformedRecordError,
    RejectReason,
    is_citable,
    record_to_paper,
    validate_shape,
)
from bio_claim_check.features.retrieval.errors import RetrievalError
from bio_claim_check.features.retrieval.query import build_query, validate_search

SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
CACHE_NAMESPACE = "europepmc.search"
CACHE_VERSION = 1
"""Bump when the request shape or the meaning of a cached response changes; old entries then miss."""

RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)
MAX_RETRY_AFTER = 60.0
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

_log = logging.getLogger(__name__)


def _not_json(token: str) -> object:
    raise ValueError(f"{token} is not JSON")


def _records(body: bytes) -> list[Mapping[str, object]]:
    """The validated result records, or `RetrievalError` for anything but the documented envelope."""
    try:
        envelope = json.loads(body, parse_constant=_not_json)
    except ValueError as exc:  # JSONDecodeError, UnicodeDecodeError, NaN/Infinity
        raise RetrievalError("Europe PMC sent a response that is not JSON") from exc
    if not isinstance(envelope, dict):
        raise RetrievalError("Europe PMC response: expected a JSON object")
    envelope = cast(dict[str, object], envelope)
    hits = envelope.get("hitCount")
    result_list = envelope.get("resultList")
    if isinstance(hits, bool) or not isinstance(hits, int) or hits < 0:
        raise RetrievalError("Europe PMC response: hitCount is missing or not a count")
    if not isinstance(result_list, dict):
        raise RetrievalError("Europe PMC response: resultList is missing")
    results = cast(dict[str, object], result_list).get("result")
    if not isinstance(results, list):
        raise RetrievalError("Europe PMC response: resultList.result is not a list")
    records = cast(list[object], results)
    if (hits > 0 and not records) or hits < len(records):
        raise RetrievalError(f"Europe PMC response: hitCount {hits} contradicts {len(records)} records")
    if not all(isinstance(r, dict) for r in records):
        raise RetrievalError("Europe PMC response: a record is not an object")
    typed = cast(list[Mapping[str, object]], records)
    try:
        for record in typed:
            validate_shape(record)
    except MalformedRecordError as exc:
        raise RetrievalError(f"Europe PMC response: malformed record ({exc})") from exc
    return typed


def _retry_after(response: httpx.Response, default: float) -> float:
    """`Retry-After` in seconds, capped; an HTTP-date or junk falls back to the default (no clock here)."""
    value = response.headers.get("Retry-After", "").strip()
    if value.isascii() and value.isdigit():
        return min(float(value), MAX_RETRY_AFTER)
    return default


class EuropePmcLiteratureSource(BaseLiteratureSource):
    """Searches Europe PMC through the cache and returns only citable papers, in Europe PMC rank order."""

    def __init__(
        self,
        client: httpx.Client,
        cache: BaseCache,
        mode: CacheMode,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._cache = cache
        self._mode = mode
        self._sleep = sleep

    @override
    def search(self, question: str, *, limit: int) -> tuple[Paper, ...]:
        validate_search(question, limit)
        params = {
            "query": build_query(question),
            "resultType": "core",
            "format": "json",
            "pageSize": str(limit),
        }
        shape: dict[str, JsonValue] = dict(params)  # every request-shaping input, nothing volatile (I34)
        key = cache_key(CACHE_NAMESPACE, CACHE_VERSION, {"url": SEARCH_URL, "params": shape})
        body = fetch_through(
            self._cache, self._mode, key, lambda: self._fetch(params), namespace=CACHE_NAMESPACE
        )
        papers: list[Paper] = []
        seen: set[str] = set()
        rejected: Counter[RejectReason] = Counter()
        for record in _records(body):
            if (reason := is_citable(record)) is not None:
                rejected[reason] += 1
                continue
            paper = record_to_paper(record)
            if paper.source_id in seen:
                rejected[RejectReason.DUPLICATE] += 1
                continue
            seen.add(paper.source_id)
            papers.append(paper)
        if rejected:
            _log.info(
                "europepmc: kept %d, rejected %s",
                len(papers),
                ", ".join(f"{r.value}={n}" for r, n in sorted(rejected.items())),
            )
        return tuple(papers[:limit])

    def _fetch(self, params: Mapping[str, str]) -> bytes:
        """One validated 200 body. Raises before returning, so nothing bad reaches the cache."""
        body = self._get(params).content
        _records(body)
        return body

    def _get(self, params: Mapping[str, str]) -> httpx.Response:
        attempts = len(RETRY_DELAYS) + 1
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                response = self._client.get(SEARCH_URL, params=params)
            except httpx.TransportError as exc:
                if last:
                    raise RetrievalError(
                        f"Europe PMC unreachable after {attempts} attempts ({type(exc).__name__})"
                    ) from exc
                _log.warning("europepmc: %s, retrying", type(exc).__name__)
                self._sleep(RETRY_DELAYS[attempt])
                continue
            except httpx.RequestError as exc:  # e.g. a body that fails to decompress: not transient
                raise RetrievalError(f"Europe PMC response could not be read ({type(exc).__name__})") from exc
            if response.status_code == 200:
                return response
            if response.status_code not in RETRY_STATUSES or last:
                raise RetrievalError(f"Europe PMC returned HTTP {response.status_code}")
            _log.warning("europepmc: HTTP %d, retrying", response.status_code)
            self._sleep(_retry_after(response, RETRY_DELAYS[attempt]))
        raise AssertionError("unreachable")  # the loop always returns or raises
