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
| A8 | As a scientist, I want every model call to take one readable path with distinct repeats, at most one repair and honest cost (unknown, never $0), so that instability and spend are measured, not hidden | ✅ (S08: engine on scripted and cached clients; S09: Foundry backends for gpt and Claude, live ping, recorded fixtures, pipeline events; prices entered by the user) |
| A10 | As a scientist, I want the Kimi deployment adapted and its structured-output support probed, so that the trap generator's model is checked like the others | ⏸ (deferred in S09 by the maintainer; stays in the catalogue, excluded from `llm ping`. S13 writes traps with `gpt-6.1-sol` instead; Kimi would add a second writer family) |
| A11 | As a maintainer, I want the Europe PMC retry helper to use `engine/llm/transport_policy`, so that there is one deterministic retry policy | ⏸ |
| A12 | As a scientist, I want the Anthropic prompt-filter error shape recorded and handled, and the billing of prompt-filtered calls confirmed, so that filtered Claude calls are counted like gpt's | ⏸ (only the OpenAI 400 `content_filter` shape is known; ADR 0014 open items) |
| A13 | As a maintainer, I want provider cache-write tokens (`input_tokens_details.cache_write_tokens`) priced once prices exist, so that cost stays honest | ⏸ (inside input; ignored while prices are `None`) |
| A14 | As a scientist, I want a failed call's spend to survive every exception path (a re-raised client error after a billed attempt; a timeout or unexpected response counted as unmeasured), so that no paid attempt drops out of `Spend` | ✅ (S11: the ledger folds events; a failure that may have reached the provider is `unmeasured`, ADR 0018) |
| A9 | As a reviewer, I want one canonical JSON serialiser, typed errors with stable documented codes and exit codes, and redacted stderr logs, so that hashes cannot drift, failures are nameable and no secret reaches a log | ✅ (S08b: no output byte, hash, golden or seal changed; central exit mapping in S16) |

## Feature B — Real adapters and the product

| Story | As a … I want … so that … | Status |
|---|---|---|
| B1 | As a user, I want cached Europe PMC retrieval, so that repeated runs make no network calls | ✅ |
| B2 | As a scientist, I want a held-out test split sealed before any tuning, so that results are not tuned to the test | ✅ (S07b: sealed; S12b: freeze v1 and the gated test export, ADR 0020; the test audit itself is the author's, before S13) |
| B2b | As a scientist, I want `surrogate_as_clinical` as a scored trap kind (biomarker or imaging result stated as a clinical benefit), so that the most common spin type in drug trials is covered | ⏸ (sieve precision too low in the consult, ~15 test candidates; deferred to H1 as a pitch example (S13 decision D5). Scoring it needs sieve v3 + a new ADR) |
| B3 | As a user, I want `bio-claim-check run "<question>"` to give a per-claim trust report | ✅ (S12a, ADR 0019: live answer, one LLM verifier call per pair, recorded run; S12b: no tuning needed, freeze v1) |
| B4 | As a user, I want the Streamlit UI layered as protocol → pure view-model → render, so that the UI logic is tested offline without Streamlit | ⏳ (split for the demo track. **S17a:** `app/ui/protocol.py` loads `Report` + `RunManifest` from `var/runs/<id>`; `run_view.py` is a pure, total function into a `RunView`; `page.py` only renders and is the one `streamlit` importer, guarded by an import-linter contract; Ask page and Trust report page; curated error-copy map with a parity test; Docker offline mode with live controls disabled. **S17b:** Benchmark page, Markdown export, trap-outcome view, and a trace view (via the ledger's run → events link) only if wanted. No streaming: the UI reads finished runs) |
| B5 | As a scientist, I want the answer agent itself to answer in self-contained claims (S10 answers in that style and flags `dangling_reference` claims), so that every claim can be checked alone | ✅ (S10, ADR 0017: Strict and Over-eager agents, abstention, flag-only self-containment, invented citations, `answer dev` on the sealed dev pool) |
| B6 | As a reviewer, I want a flagged dangling claim rewritten to stand alone with the original kept beside it (an audit trail), so that the rewrite is visible and reversible | ⏸ (S10 flags only, maintainer decision; a rewrite changes meaning) |
| B7 | As a reviewer, I want a stored report rejected if its `dangling_reference` findings differ from the ones the check re-derives, so that a tampered artifact cannot look cleaner | ⏸ (S10 implementation review #6: needs the check outside `checks`, since slices never import each other; revisit with the S15 report) |

## Feature C — Measurement

| Story | As a … I want … so that … | Status |
|---|---|---|
| C1 | As a scientist, I want planted traps with ground truth, so that I know what the verifier catches | ⏳ (S13, ADR 0022: generator, audit sheet, `apply-audit` and `traps verify` built on dev with predeclared truth and metrics; the dev set lands after the author's audit; test traps need a later ADR and the test audit) |
| C2 | As a reviewer, I want simple baselines next to every verifier, so that I can see whether the LLM adds anything | ⏳ |
| C3 | As a reviewer, I want a pre-registered protocol and paired, clustered statistics, so that the numbers are honest | ⏳ |
| C4 | As a scientist, I want the negation detector's precision measured on labelled pairs, so that the share of correct null results sent to `needs_review` is known | ⏸ (needs labels, S18; S10's rule is conservative on purpose. S12b dev: 4/4 `negated_supported` pairs were `claim_shares_negation`, i.e. a correct negative claim blocked; a fix needs its own ADR) |
| C5 | As a scientist, I want to know whether Over-eager actually overstates on the answer model, so that the mode comparison measures something | ⏸ (S10 dev, author-read: gpt-6.1-sol kept hedging after one prompt revision; revisit at the proof checkpoint) |
| C6 | As a reviewer, I want the verifier challenge set re-labelled by an independent human rater, so that its labels are not one person's call | ⏸ (S12b: one human rater plus an AI blind second rater, 16/16; not an expert panel, ADR 0020) |

## Feature D — Ship

| Story | As a … I want … so that … | Status |
|---|---|---|
| D1 | As a researcher, I want docs, a data card and a replay bundle, so that I can reproduce the tables | ⏳ |
| D2 | As anyone, I want a tagged 1.0 release that runs with one command | ⏳ |
| D3 | As the maintainer, I want a safe hackathon demo early (demo track: S13 → proof → S17a → H1), so that the remaining measurement sessions are not rushed before the event | ⏳ (H1 decides what is shown on the day and must respect option C: no claimcheck results on the day, no numbers; trap papers come from dev or outside the corpus, checked against the test split by id only) |

## Why this order

| Step | Why now |
|---|---|
| Guardrails before code | Agent-written code is cheapest to keep in shape from the first file |
| Fakes end to end before providers | Proves the structure without network, cost or flakiness |
| Port shape before the first backend | Moving 3 ports is cheap; moving them after S06/S08 would mean 3 more ports and 5 more implementations |
| LLM engine before provider SDKs | The runner, cache key and cost rules are tested without network or money; S09 only adds transport |
| Sealed split before prompt tuning | Tuning on the test split would invalidate every result |
| Baselines and protocol before the study | The comparison and analysis are fixed before the numbers exist |
| Demo track (S17a, H1) before S14 | A safe demo early; S17a is the final layered UI reading stable contracts, so S17b only adds pages |
