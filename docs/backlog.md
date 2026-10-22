# Backlog

**Source of truth:** the code decides what is done. This file is updated only when a story completes or
a story is added. Design detail lives in the ADRs and the per-session dev-log, not here.

**Legend:** ✅ done · 🚧 in progress · ⏳ next · ⏸ parked · ⛔ blocked

## Feature A — Foundation

| Story | As a … I want … so that … | Status |
|---|---|---|
| A1 | As a reviewer, I want one `make verify` gate, a locked environment and secret scanning, so that every quality claim is checkable | ✅ |
| A2 | As a maintainer, I want import rules that are proven to fire, so that the architecture cannot silently erode | ✅ |
| A2b | As a maintainer, I want no import cycles, driver-free core rings, classified dependencies and a generated dependency graph, so that the structure is checkable at a glance | ✅ |
| A3 | As a researcher, I want the licence, citation and contribution path in place from the start, so that I can reuse and credit the work | ✅ |
| A4 | As a developer, I want quote location that keeps operators and word boundaries, so that `p < 0.05` never matches `p > 0.05` | ✅ |
| A5 | As a developer, I want typed domain contracts with two separate verdict axes, so that the model's judgement and code's evidence check never overwrite each other | ✅ |
| A5b | As a researcher, I want a validated rule-pack format with a shipped seed pack, so that I can propose how papers in my field get misread without writing code | ✅ |
| A6 | As a reviewer, I want an end-to-end run on fakes, so that the structure is proven before any provider exists | ✅ |
| A7 | As a contributor, I want one obvious shape for ports and backends and rules that describe kinds, so that a new slice or backend passes the architecture checks without anyone editing them | ✅ |
| A8 | As a scientist, I want every model call to take one readable path with distinct repeats, at most one repair and honest cost (unknown, never $0), so that instability and spend are measured, not hidden | ✅ (S08: engine on scripted and cached clients; provider backends in S09; prices entered by the user) |
| A9 | As a reviewer, I want one canonical JSON serialiser, typed errors with stable documented codes and exit codes, and redacted stderr logs, so that hashes cannot drift, failures are nameable and no secret reaches a log | ✅ (S08b: no output byte, hash, golden or seal changed; central exit mapping in S16) |

## Feature B — Real adapters and the product

| Story | As a … I want … so that … | Status |
|---|---|---|
| B1 | As a user, I want cached Europe PMC retrieval, so that repeated runs make no network calls | ✅ |
| B2 | As a scientist, I want a held-out test split sealed before any tuning, so that results are not tuned to the test | ✅ (S07b: sealed; test audit by the author after the S12 prompt freeze) |
| B2b | As a scientist, I want `surrogate_as_clinical` as a scored trap kind (biomarker or imaging result stated as a clinical benefit), so that the most common spin type in drug trials is covered | ⏸ (sieve precision too low in the consult, ~15 test candidates; S13 generates it as an unscored pitch example. Scoring it needs sieve v3 + a new ADR) |
| B3 | As a user, I want `bio-claim-check run "<question>"` to give a per-claim trust report | ⏳ |

## Feature C — Measurement

| Story | As a … I want … so that … | Status |
|---|---|---|
| C1 | As a scientist, I want planted traps with ground truth, so that I know what the verifier catches | ⏳ |
| C2 | As a reviewer, I want simple baselines next to every verifier, so that I can see whether the LLM adds anything | ⏳ |
| C3 | As a reviewer, I want a pre-registered protocol and paired, clustered statistics, so that the numbers are honest | ⏳ |

## Feature D — Ship

| Story | As a … I want … so that … | Status |
|---|---|---|
| D1 | As a researcher, I want docs, a data card and a replay bundle, so that I can reproduce the tables | ⏳ |
| D2 | As anyone, I want a tagged 1.0 release that runs with one command | ⏳ |

## Why this order

| Step | Why now |
|---|---|
| Guardrails before code | Agent-written code is cheapest to keep in shape from the first file |
| Fakes end to end before providers | Proves the structure without network, cost or flakiness |
| Port shape before the first backend | Moving 3 ports is cheap; moving them after S06/S08 would mean 3 more ports and 5 more implementations |
| LLM engine before provider SDKs | The runner, cache key and cost rules are tested without network or money; S09 only adds transport |
| Sealed split before prompt tuning | Tuning on the test split would invalidate every result |
| Baselines and protocol before the study | The comparison and analysis are fixed before the numbers exist |
