# Backlog

**Source of truth:** the code decides what is done. This file is updated only when a story completes or
a story is added. Design detail lives in the ADRs and the per-session dev-log, not here.

**Legend:** ✅ done · 🚧 in progress · ⏳ next · ⏸ parked · ⛔ blocked

## Feature A — Foundation

| Story | As a … I want … so that … | Status |
|---|---|---|
| A1 | As a reviewer, I want one `make verify` gate, a locked environment and secret scanning, so that every quality claim is checkable | ✅ |
| A2 | As a maintainer, I want import rules that are proven to fire, so that the architecture cannot silently erode | ✅ |
| A3 | As a researcher, I want the licence, citation and contribution path in place from the start, so that I can reuse and credit the work | ✅ |
| A4 | As a developer, I want quote location that keeps operators and word boundaries, so that `p < 0.05` never matches `p > 0.05` | ⏳ |
| A5 | As a developer, I want typed domain contracts with two separate verdict axes, so that the model's judgement and code's evidence check never overwrite each other | ⏳ |
| A6 | As a reviewer, I want an end-to-end run on fakes, so that the structure is proven before any provider exists | ⏳ |

## Feature B — Real adapters and the product

| Story | As a … I want … so that … | Status |
|---|---|---|
| B1 | As a user, I want cached Europe PMC retrieval, so that repeated runs make no network calls | ⏳ |
| B2 | As a scientist, I want a held-out test split sealed before any tuning, so that results are not tuned to the test | ⏳ |
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
| Sealed split before prompt tuning | Tuning on the test split would invalidate every result |
| Baselines and protocol before the study | The comparison and analysis are fixed before the numbers exist |
