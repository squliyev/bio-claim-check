"""Europe PMC backend over MockTransport: request shape, post-filter, retries, cache (ADR 0008/0009)."""

import hashlib

import httpx
import pytest
from tests.support.europepmc import envelope, fixture, good_record, harness, mixed_records, ok

from bio_claim_check.engine.cache.in_memory_cache import InMemoryCache
from bio_claim_check.engine.cache.policy import CacheMissError, CacheMode
from bio_claim_check.features.retrieval.citable import QUERY_FILTERS, RejectReason
from bio_claim_check.features.retrieval.errors import NotCitableError, RetrievalError
from bio_claim_check.features.retrieval.europe_pmc_literature_source import (
    MAX_RETRY_AFTER,
    MIN_INTERVAL,
    SEARCH_URL,
)

pytestmark = pytest.mark.unit

MIXED = envelope(mixed_records())


def test_the_post_filter_keeps_only_citable_unique_papers_in_rank_order() -> None:
    h = harness(ok(MIXED))
    papers = h.source.search("plaque", limit=25)
    assert [p.source_id for p in papers] == [
        "MED:90000001",
        "MED:90000002",
        "MED:90000003",
        "MED:90000004",
        "MED:90000009",
    ]
    assert [p.retracted for p in papers] == [False, False, True, True, False]
    assert (
        papers[1].title == "HX-15 in early cognitive decline: a fictional trial"
    )  # first of a duplicate wins


def test_rejections_are_counted_in_the_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    harness(ok(MIXED)).source.search("plaque", limit=25)
    assert (
        "kept 5, rejected duplicate=1, excluded_type=1, no_abstract=1, not_med=1, wrong_language=1"
        in caplog.text
    )


def test_limit_truncates_after_filtering() -> None:
    assert len(harness(ok(MIXED)).source.search("plaque", limit=2)) == 2


@pytest.mark.parametrize(
    "question",
    [
        '"amyloid beta" AND (mice OR rats)',
        "a) OR (b",
        "TITLE:metformin",
        "β-amyloid \u2013 Ünïcode",
        "x:y\"z'",
    ],
)
def test_the_query_is_sent_verbatim_with_the_filters(question: str) -> None:
    h = harness(ok(envelope([])))
    h.source.search(question, limit=7)
    (request,) = h.server.requests
    assert request.method == "GET"
    assert str(request.url.copy_with(query=None)) == SEARCH_URL
    assert dict(request.url.params) == {
        "query": f"({question}) AND {QUERY_FILTERS}",
        "resultType": "core",
        "format": "json",
        "pageSize": "7",
    }


def test_a_hostile_query_cannot_admit_an_uncitable_record() -> None:
    preprint = mixed_records()[5]
    assert preprint["source"] == "PPR"
    assert harness(ok(envelope([preprint]))).source.search("a) OR (b", limit=5) == ()


def test_no_hits_is_empty_not_an_error() -> None:
    assert harness(ok(envelope([]))).source.search("nothing", limit=5) == ()


@pytest.mark.parametrize(
    ("question", "limit"),
    [("", 5), ("   ", 5), ("ok", 0), ("ok", 101), ("ok", -1), ("tab\there", 5), ("nul\x00", 5), ("ok", True)],
)
def test_bad_input_is_a_value_error_before_any_request(question: str, limit: int) -> None:
    h = harness()
    with pytest.raises(ValueError, match=r"question|limit"):
        h.source.search(question, limit=limit)
    assert h.server.requests == []


# ---------------------------------------------------------------- retries


def test_retry_after_is_honoured_and_capped() -> None:
    h = harness(
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(503, headers={"Retry-After": "9999"}),
        httpx.Response(503, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
        ok(envelope([good_record()])),
    )
    assert len(h.source.search("q", limit=1)) == 1
    assert h.sleeps == [2.0, MAX_RETRY_AFTER, 4.0]


def test_a_zero_retry_after_still_waits_the_minimum_interval() -> None:
    h = harness(httpx.Response(429, headers={"Retry-After": "0"}), ok(envelope([good_record()])))
    assert len(h.source.search("q", limit=1)) == 1
    assert h.sleeps == [MIN_INTERVAL]


def test_consecutive_requests_are_throttled_but_cache_hits_are_not() -> None:
    h = harness(ok(MIXED), ok(MIXED), ok(MIXED))
    h.source.search("plaque", limit=25)
    assert h.sleeps == []
    h.source.search("plaque", limit=25)
    assert h.sleeps == []
    h.source.search("tangle", limit=25)
    h.source.search("amyloid", limit=25)
    assert h.sleeps == [MIN_INTERVAL, MIN_INTERVAL]
    assert len(h.server.requests) == 3


def test_a_failed_search_still_counts_for_the_throttle() -> None:
    h = harness(httpx.Response(400), ok(MIXED))
    with pytest.raises(RetrievalError):
        h.source.search("plaque", limit=25)
    h.source.search("tangle", limit=25)
    assert h.sleeps == [MIN_INTERVAL]


def test_transient_failures_back_off_deterministically() -> None:
    h = harness(
        httpx.ConnectTimeout("slow"),
        httpx.Response(500),
        httpx.ReadError("reset"),
        ok(envelope([good_record()])),
    )
    assert len(h.source.search("q", limit=1)) == 1
    assert h.sleeps == [1.0, 2.0, 4.0]
    assert len(h.server.requests) == 4


@pytest.mark.parametrize(
    "replies",
    [
        [httpx.Response(503)] * 4,
        [httpx.ConnectError("down")] * 4,
    ],
)
def test_exhausted_retries_raise_and_cache_nothing(replies: list[httpx.Response | Exception]) -> None:
    h = harness(*replies)
    with pytest.raises(RetrievalError, match=r"HTTP 503|unreachable after 4 attempts"):
        h.source.search("q", limit=1)
    assert len(h.server.requests) == 4
    h2 = harness(ok(envelope([])), cache=h.cache)
    h2.source.search("q", limit=1)
    assert len(h2.server.requests) == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_are_not_retried(status: int) -> None:
    h = harness(httpx.Response(status))
    with pytest.raises(RetrievalError, match=f"HTTP {status}"):
        h.source.search("q", limit=1)
    assert len(h.server.requests) == 1
    assert h.sleeps == []


# ---------------------------------------------------------------- malformed responses are never cached


def _malformed_bodies() -> list[bytes]:
    good = fixture("search_empty.json")
    bad_record = good_record()
    bad_record["pubTypeList"] = {"pubType": "Journal Article"}
    return [
        b"<html>maintenance</html>",
        b"\xff\xfe",
        b"[]",
        b'{"hitCount": 1}',
        b'{"hitCount": "1", "resultList": {"result": []}}',
        b'{"hitCount": true, "resultList": {"result": []}}',
        b'{"hitCount": 0, "resultList": {"result": {}}}',
        b'{"hitCount": 0, "resultList": []}',
        envelope([], hit_count=3),
        envelope([good_record()], hit_count=0),  # a total count can never be below the page
        envelope(mixed_records()[:2], hit_count=1),
        b'{"hitCount": 0, "resultList": {"result": []}, "x": NaN}',
        b'{"hitCount": 0, "resultList": {"result": []}, "x": Infinity}',
        b'{"hitCount": 0, "resultList": {"result": []}, "x": -Infinity}',
        envelope([bad_record]),
        b'{"hitCount": 1, "resultList": {"result": ["x"]}}',
        str(good).encode(),  # a Python repr, not JSON
    ]


@pytest.mark.parametrize("body", _malformed_bodies())
def test_a_malformed_200_raises_and_leaves_the_cache_empty(body: bytes) -> None:
    cache = InMemoryCache()
    h = harness(ok(body), cache=cache)
    with pytest.raises(RetrievalError, match="Europe PMC"):
        h.source.search("q", limit=1)
    h2 = harness(ok(envelope([])), cache=cache)
    assert h2.source.search("q", limit=1) == ()
    assert len(h2.server.requests) == 1


def test_an_undecodable_body_is_a_retrieval_error_not_retried() -> None:
    stream = httpx.ByteStream(b"not gzip at all")  # decoded inside the client, as on the wire
    broken = httpx.Response(200, stream=stream, headers={"Content-Encoding": "gzip"})
    h = harness(broken)
    with pytest.raises(RetrievalError, match="could not be read"):
        h.source.search("q", limit=1)
    assert (len(h.server.requests), h.sleeps) == (1, [])


# ---------------------------------------------------------------- cache


def test_a_second_identical_search_makes_no_request() -> None:
    h = harness(ok(MIXED))
    first = h.source.search("plaque", limit=25)
    assert h.source.search("plaque", limit=25) == first
    assert len(h.server.requests) == 1


@pytest.mark.parametrize(("question", "limit"), [("plaque!", 25), ("plaque", 24)])
def test_any_request_change_misses(question: str, limit: int) -> None:
    h = harness(ok(MIXED), ok(MIXED))
    h.source.search("plaque", limit=25)
    h.source.search(question, limit=limit)
    assert len(h.server.requests) == 2


def test_read_only_never_touches_the_network() -> None:
    h = harness(mode=CacheMode.READ_ONLY)
    with pytest.raises(CacheMissError):
        h.source.search("plaque", limit=5)
    assert h.server.requests == []


def test_read_only_replays_what_read_write_stored() -> None:
    cache = InMemoryCache()
    live = harness(ok(MIXED), cache=cache).source.search("plaque", limit=25)
    replay = harness(cache=cache, mode=CacheMode.READ_ONLY)
    assert replay.source.search("plaque", limit=25) == live


def test_off_always_fetches_and_never_writes() -> None:
    cache = InMemoryCache()
    h = harness(ok(MIXED), ok(MIXED), cache=cache, mode=CacheMode.OFF)
    h.source.search("plaque", limit=25)
    h.source.search("plaque", limit=25)
    assert len(h.server.requests) == 2
    with pytest.raises(CacheMissError):
        harness(cache=cache, mode=CacheMode.READ_ONLY).source.search("plaque", limit=25)


def test_the_cache_key_ignores_request_headers() -> None:
    """The User-Agent (with the contact email) does not shape the response, so it is not in the key."""
    cache = InMemoryCache()
    harness(ok(MIXED), cache=cache).source.search("plaque", limit=25)
    assert harness(cache=cache, mode=CacheMode.READ_ONLY).source.search("plaque", limit=25)


# ---------------------------------------------------------------- response hash


def test_the_response_hash_is_the_sha256_of_the_served_body() -> None:
    h = harness(ok(MIXED))
    h.source.search("plaque", limit=25)
    assert h.source.response_sha256("plaque", 25) == hashlib.sha256(MIXED).hexdigest()


@pytest.mark.parametrize("mode", [CacheMode.READ_ONLY, CacheMode.OFF])
def test_the_response_hash_is_recorded_on_a_cache_hit_and_with_the_cache_off(mode: CacheMode) -> None:
    cache = InMemoryCache()
    harness(ok(MIXED), cache=cache).source.search("plaque", limit=25)
    h = harness(*([ok(MIXED)] if mode is CacheMode.OFF else []), cache=cache, mode=mode)
    h.source.search("plaque", limit=25)
    assert h.source.response_sha256("plaque", 25) == hashlib.sha256(MIXED).hexdigest()


@pytest.mark.parametrize(("question", "limit"), [("never searched", 25), ("plaque", 24)])
def test_the_response_hash_of_an_unmade_search_is_a_key_error(question: str, limit: int) -> None:
    h = harness(ok(MIXED))
    h.source.search("plaque", limit=25)
    with pytest.raises(KeyError):
        h.source.response_sha256(question, limit)


def _med(pmid: str, *, source: str = "MED") -> dict[str, object]:
    record = good_record()
    record.update(pmid=pmid, source=source)
    return record


def test_retraction_status_asks_for_exact_ids_without_the_citable_filters_or_the_cache() -> None:
    h = harness(ok(envelope([_med("90000001")])), ok(envelope([_med("90000001")])))
    for _ in range(2):
        h.source.retraction_status(("MED:90000001", "MED:90000002"))
    assert len(h.server.requests) == 2  # never cached
    params = dict(h.server.requests[0].url.params)
    assert params["query"] == "(EXT_ID:90000001 AND SRC:MED) OR (EXT_ID:90000002 AND SRC:MED)"
    assert QUERY_FILTERS not in params["query"]
    assert params["pageSize"] == "100"


def test_retraction_status_chunks_ids_by_one_hundred_and_skips_non_med_ids() -> None:
    ids = tuple(f"MED:{90000000 + i}" for i in range(201))
    h = harness(ok(envelope([])), ok(envelope([])), ok(envelope([])))
    rows = h.source.retraction_status(("FAKE:1", *ids))
    assert [len(r.url.params["query"].split(" OR ")) for r in h.server.requests] == [100, 100, 1]
    assert {r.retracted for r in rows} == {None}
    assert rows[0].source_id == "FAKE:1"


def test_retraction_status_of_only_non_med_ids_makes_no_request() -> None:
    h = harness()
    assert [r.retracted for r in h.source.retraction_status(("FAKE:1",))] == [None]


@pytest.mark.parametrize(
    ("records", "match"),
    [
        ([_med("90000009")], "not asked for"),
        ([_med("90000001", source="PMC")], "not asked for"),
        ([_med("90000001"), _med("90000001")], "twice"),
    ],
    ids=["unexpected_id", "wrong_source", "duplicate"],
)
def test_retraction_status_refuses_an_answer_it_did_not_ask_for(
    records: list[dict[str, object]], match: str
) -> None:
    with pytest.raises(RetrievalError, match=match):
        harness(ok(envelope(records))).source.retraction_status(("MED:90000001",))


def test_retraction_status_refuses_a_second_page() -> None:
    with pytest.raises(RetrievalError, match="more hits"):
        harness(ok(envelope([_med("90000001")], hit_count=2))).source.retraction_status(("MED:90000001",))


# ---------------------------------------------------------------- fetch (S17a, ADR 0025)


def _record(pmid: str) -> dict[str, object]:
    return next(r for r in mixed_records() if r.get("pmid") == pmid and r.get("source") == "MED")


def test_fetch_asks_for_exactly_one_med_id() -> None:
    h = harness(ok(envelope([_record("90000001")])))
    h.source.fetch("MED:90000001")
    params = h.server.requests[0].url.params
    assert params["query"] == "(EXT_ID:90000001 AND SRC:MED)"
    assert (params["resultType"], params["pageSize"]) == ("core", "2")


@pytest.mark.parametrize(
    "source_id", ["MED:abc", "MED:0", "MED:01", "MED:1 OR x", "MED:1234567890", "PMC:123", "FAKE:1", "MED:"]
)
def test_fetch_refuses_anything_but_a_pmid_before_any_request(source_id: str) -> None:
    h = harness()
    with pytest.raises(ValueError, match=r"MED:<pmid>"):
        h.source.fetch(source_id)
    assert h.server.requests == []


def test_fetch_of_a_record_that_is_not_citable_names_the_reason() -> None:
    h = harness(ok(envelope([_record("90000007")])))
    with pytest.raises(NotCitableError) as caught:
        h.source.fetch("MED:90000007")
    assert caught.value.reason is RejectReason.NO_ABSTRACT


def test_fetch_refuses_a_record_for_another_id() -> None:
    h = harness(ok(envelope([_record("90000002")])))
    with pytest.raises(RetrievalError, match="not asked for"):
        h.source.fetch("MED:90000001")


def test_fetch_refuses_more_than_one_record() -> None:
    h = harness(ok(envelope([_record("90000001"), _record("90000001")])))
    with pytest.raises(RetrievalError, match="single id"):
        h.source.fetch("MED:90000001")


def test_fetch_is_cached_and_replays_offline() -> None:
    cache = InMemoryCache()
    first = harness(ok(envelope([_record("90000001")])), cache=cache).source.fetch("MED:90000001")
    replay = harness(cache=cache, mode=CacheMode.READ_ONLY)
    assert replay.source.fetch("MED:90000001") == first
    assert replay.server.requests == []
    with pytest.raises(CacheMissError):
        replay.source.fetch("MED:90000002")
