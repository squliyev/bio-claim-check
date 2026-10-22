# ADR 0009 — Cache and replay: raw responses keyed by request; read-only fails closed

- **Status:** Accepted
- **Date:** 2026-10-20
- **Supersedes / Extends:** —
- **Related:** 0007, 0008
- **Enforced by:** `tests/contract/test_cache_contract.py` (every cache backend) · `tests/unit/engine/test_cache.py` · `tests/unit/features/test_europe_pmc_literature_source.py::test_read_only_never_touches_the_network` · `tests/unit/app/test_retrieve_cli.py::test_read_only_miss_exits_3_without_a_request`

## Context

A result other people can re-run needs the exact inputs it was computed from. Europe PMC's ranking and
records change over time, and LLM calls (S08) are neither free nor deterministic. Without a cache,
"re-running" a study means asking different questions of a different corpus. A cache that silently
fetches on a miss is just as bad: a replay that quietly went to the network is not a replay.

## Decision

- **What is stored:** the raw response bytes, after they pass validation (envelope and every record's
  shape). Anything that fails validation, and every failed request, stores nothing.
- **Key:** `sha256` of canonical JSON (`sort_keys`, no NaN) over a namespace, a version and every input
  that shapes the response (for Europe PMC: query, filters, page size, result type). Nothing volatile:
  no time, no headers, no contact address. Changing what a request means bumps the version.
- **First write wins.** A key is written once and never overwritten, so a replay sees exactly the
  response the original run saw, including its ranking.
- **Modes** (`BCC_CACHE_MODE`, the engine's `CacheMode`):
  - `read-write` (default): a hit is served; a miss fetches, validates and stores.
  - `read-only`: a hit is served; a miss raises `CacheMissError` and **never** fetches. A missing cache
    file is not created. This is the replay mode.
  - `off`: always fetches; never reads or writes.
- **Backends** sit beside `BaseCache` (ADR 0007): `InMemoryCache` and `SqliteCache` (one table, WAL,
  `INSERT OR IGNORE`; read-only opens the file with SQLite's `mode=ro`). Both pass one contract suite.
  A corrupt cache file is a `CacheError` (CLI exit 5), never a silent miss.
- **A cached response is a snapshot.** It freezes everything, including retraction status. The CLI says
  so ("retraction status is as of the first fetch"). Expiry or refresh is rejected: it would break
  first-write-wins replay and needs a clock in the core (I29).

## Consequences

- **Positive:** a second identical run makes no requests; a read-only replay either reproduces the run
  or stops with exit 3. The cache is one file under the git-ignored `var/`.
- **Negative (accepted):** a stale snapshot can hide a later retraction. S12 re-checks retraction for
  every cited paper with an uncached lookup and the report says when it could not.
- **Negative (accepted):** the cache grows without bound; deleting `var/cache.sqlite` is the reset.
- **Follow-ups:** done in S08: LLM response keys include a repeat index and the pinned model identity
  (ADR 0012). Open: a later session exports the cache entries a
  report used as a scrubbed replay bundle.
