# Roadmap

**What this is:** the public, condensed plan from an empty repo to the 1.0 release. Each session (Sxx) is
sized for one agent-assisted working session. The detailed design of finished sessions lives in their
ADRs and in `docs/dev-log/Sxx.md`; this file only says what each session is for and how it is gated.
Story status lives in [backlog.md](backlog.md). Where to start a new session: [HANDOFF.md](HANDOFF.md).

**Status (S10 done):** S01–S10 are done. Next is **S11**, the run record (events, manifest, ledger).

## Product

"Does this agent's answer hold up?" An open-source claim checker for life-science agents.

1. Answer a research question from Europe PMC abstracts (MEDLINE only, identity `MED:<pmid>`).
2. Check every claim against the abstract it cites. A verifier model labels each (claim, source) pair
   `supported`, `overstated` (with a reason from a spin taxonomy), `contradicted` or `not_in_source`.
3. Code then checks that the quoted evidence really is in the abstract (fail closed) and derives a
   disposition: `passed`, `needs_review`, `failed` or `flagged` ([ADR 0006](adr/0006-two-axis-verdict-and-disposition.md)).
4. Planted traps measure what the verifier catches (E1) and how often it raises a false alarm (E2) on a
   held-out test split that was sealed before any tuning ([ADR 0010](adr/0010-evaluation-corpus-and-split.md)).

## Approach

- **Evaluation rigour is the product.** A sealed held-out split, pre-registration, a false-alarm rate
  next to every catch rate, paired statistics with a cluster bootstrap by source abstract, simple
  baselines, a cross-family model matrix, an external anchor, and reproducibility claims we can prove.
- **Engineering discipline that is enforced, not described.** Rings, ports as abstract base classes,
  a composition root, shared contract suites, ADRs with an `Enforced by:` line, and invariants that each
  have a guard and a test ([invariants.md](invariants.md)).
- **No agent framework.** The pipeline is a fixed DAG over the official provider SDKs, so every request
  is readable and replayable ([ADR 0004](adr/0004-no-agent-framework.md)).
- **Honest numbers.** Unknown cost is "unpriced", never $0. Unreported token counts are `None`, never 0.
  Author-labelled data is never called expert-labelled. Dev-split numbers are exploratory only.

## Hackathon relationship (disclosed)

This project was built before the hackathon it was pitched at, and that is stated openly. On the day, a
clean rebuild happens in a separate, empty repo. Rules that researchers write on the day are theirs: they
can be contributed here as their own credited rule pack. No results from this repo are shown on the day.

## Per-session process (every session)

1. **Plan first.** Before planning, read the internal reference notes for that session (kept outside the
   repo). The plan contains:
   - code sketches of every new interface, model and key function;
   - an ASCII tree of every file created (`+`), changed (`~`) or deleted (`−`), each with `# because …`;
   - a decisions table, edge-case tests, new invariants and ADRs, out of scope and exit criteria.
2. **Ask** the maintainer about real decisions; never guess.
3. **One plan review** by a reviewer whose only brief is to hunt for problems: a paranoid senior
   engineer, read-only, looking for bugs, hidden failure paths, rule and ADR breaches and dishonest
   measurement. The reviewer lists **every** suggestion, with no cap. The author triages each one (adopt,
   adapt to a minimal version, or reject as over-engineering, with a one-line reason), then does a
   balance pass that cuts anything whose cost exceeds the risk it removes.
4. **Implement** in the planned order (characterisation tests first when refactoring). `make verify`
   must be green.
5. **One implementation review** of the actual diff by the same reviewer brief, uncapped, triaged the
   same way. Fixes are verified by `make verify` and targeted tests, not re-reviewed.
6. **Docs:** ADRs and their index row, invariants, glossary, error codes, backlog, `docs/dev-log/Sxx.md`
   with both triage tables, `make graph` / `make schemas` when imports or contracts change.
7. **IP and secret scans** clean, commit, push, CI green.

## Sessions

### Phase A — Foundation

| Session | Scope | Status |
|---|---|---|
| S01 | Tooling skeleton: uv, ruff, pyright strict, pytest, Makefile, pre-commit + gitleaks, SHA-pinned CI, Docker | ✅ |
| S02 | Architecture guardrails (import-linter contracts proven to fire), governance docs, ADRs 0001–0004 | ✅ |
| S02b | No cycles, driver-free core, classified dependencies, generated dependency graph | ✅ |
| S03 | Text core: `clean_abstract`, fail-closed `locate_quote`, `near_match` (routing only) | ✅ |
| S04 | Domain contracts, two-axis verdict, total disposition table, rule-pack schema | ✅ |
| S05 | Walking skeleton: `run --fake` end to end through real ports | ✅ |
| S05b | Ports as ABC base classes, backends beside their base, transport-only infrastructure | ✅ |

### Phase B — Real adapters and the product

| Session | Scope | Status |
|---|---|---|
| S06 | Europe PMC backend, content-addressed cache, read-only replay, shared contract suites, network block | ✅ |
| S07a | Corpus spec, eligibility sieve, cluster split, deterministic `corpus build` | ✅ |
| S07b | Sieve v2, pre-registration tag, frozen and sealed dataset, dev audit tooling | ✅ |
| S08 | LLM engine core: runner, processors, one repair, cache key with repeat index and model identity, honest cost | ✅ |
| S08b | Retrofit: canonical JSON, typed errors with codes, exit-code enum, redacted logging, unreported reasoning = `None` | ✅ |
| S09 | Provider adapters, the LLM agent base and the pipeline event vocabulary (see below) | ✅ |
| S10 | Answer agent (Strict / Over-eager, stated non-scope, abstention), negation and self-containment checks, invented citations; tuned on dev sources only | ✅ |
| S11 | `events.jsonl` sink and run events (the vocabulary and emitters landed in S09), manifest, budgets, append-only ledger (incl. failed and cancelled runs), byte-identical replay | ⏳ next |
| S12 | Verifier prompt, context isolation, dev smoke gold set in CI, model-family independence, first live `run`, retraction re-check; tag `prompts-frozen-v1` | |

### Phase C — Measurement

| Session | Scope |
|---|---|
| (maintainer) | Test-split eligibility audit and unanswerable check, only after `prompts-frozen-v1` |
| S13 | Trap generator: rule floor + model traps within eligibility, validity gate, audit sheet, parent pairing, structural leakage test |
| Proof checkpoint | Catch and false-alarm rate per trap kind on dev (exploratory, go / adjust) |
| S14 | Baselines: AlwaysFlag, MeSH-cue, optional NLI; shared verifier contract suite |
| S15 | Related work (spin, exaggeration NLP, SciFact family), pre-registered `protocol.md`, tag `protocol-v1`, readiness checklist |
| S16 | Benchmark harness and statistics (cluster bootstrap, Newcombe paired, McNemar, Holm, Wilson) |
| S17 | Trust report and Streamlit UI (offline demo from cache) |
| S18 | Annotation workflow and agreement (κ with raw agreement, author vs external labels) |
| S19 | Study run on the sealed test split |
| S20 | External anchor (SciFact, evaluation only) and honest write-up |

### Phase D — Ship

| Session | Scope |
|---|---|
| S21 | Hardening: error taxonomy, chaos tests, `pip-audit`, history secret scan, structural `runs prune` |
| S22 | Documentation site (mkdocs on Read the Docs) |
| S23 | Dataset and scrubbed replay bundle, `hydrate` with drift report, Zenodo / HF cards, preprint draft |
| S24 | 1.0 release: public repo, DOI, credits |
| H1 | Hackathon prep: trap papers, offline demo, pitch, disclosure |

### S09 — provider adapters (done)

- An OpenAI-compatible client for the Azure AI Foundry `/openai/v1` surface (strict `json_schema`
  structured output) and an Anthropic client via `AnthropicFoundry` (forced tool use). Ollama pinned by
  digest and the Anthropic API directly are optional.
- Backends sit beside `BaseLlmClient` in `engine/llm/` and hold all provider-specific knowledge.
- **Bindings from earlier sessions:**
  - Usage is normalised so that reasoning ⊆ output and cached input ⊆ input. Reasoning tokens are `None`
    when the provider does not report them. One test per provider's raw usage shape.
  - Reasoning is never replayed. Model identity is part of the cache key.
  - `model_version` is pinned and supplied by the maintainer; no invented ids or prices.
  - Content-filtered responses are counted as failures, never hidden.
  - Structured-output support for each model is probed and recorded; where strict output is missing,
    validate + repair and record the repair rate.
  - Request shapes come from the official SDK documentation and our own scrubbed recordings.
- `bio-claim-check llm ping` checks every deployment live. ADR 0014 records pinned model ids and the
  structured-output support matrix.
- **Exit:** live ping passes for every deployment; the shared LLM client contract suite passes offline on
  recorded fixtures for each provider.
- **Done (see [dev-log S09](dev-log/S09.md)):** gpt-6.1-sol and claude-opus-4-8 pass live ping; Kimi
  deferred (backlog A10). Pulled forward by the maintainer: the `BaseLlmAgent` base (ADR 0015) and the
  pipeline event vocabulary with its emitters and an injected clock (ADR 0016). S11 keeps the
  `events.jsonl` sink, run events, manifest, ledger and budgets.

### S10 — answer agent (done)

- Strict and Over-eager answer agents with their own prompt constants and stated non-scope; Strict
  abstains with an empty answer. Claim ids and citation defects are handled by code, never by a repair
  turn. Self-containment is flagged (`dangling_reference`), not rewritten. Negation is one conservative,
  versioned detector, so a pair can be `passed` only when its evidence sentence has no negation.
- `bio-claim-check answer dev QUESTION_ID --mode strict|over_eager` answers from the sealed dev pool only
  and counts every drop (ADR 0017).
- **Done (see [dev-log S10](dev-log/S10.md)):** all 8 dev questions ran live in both modes; Strict
  abstained on both unanswerable questions. Over-eager on gpt-6.1-sol hedged more than intended
  (author-read); recorded, not chased.

## Dependencies

```
S01 → … → S07b → S08 → S08b → S09 → S10 → S11 → S12 → (test audit) → S13 → proof → S14 → S15 → S16
    → {S17, S18} → S19 → S20 → S21 → S22 → S23 → S24
```

- The sealed split (S07b) precedes any prompt tuning (S10).
- `protocol-v1` (S15) precedes the study run (S19).
- Demoable points: S05 (fakes), S12 (real product), S17 (UI).

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| A lazy verifier (flags everything, paraphrases quotes) scores well | Two-axis verdict, E1 next to E2, AlwaysFlag baseline |
| Zero-variance repeats | Repeat index in the cache key, with a contract test |
| Tuning on the test set | Split sealed before tuning; test audit after the prompt freeze; protocol hashes |
| Overstated n from clustered traps | Cluster split, cluster bootstrap |
| "A MeSH rule does as well" | Baselines reported side by side |
| Single-labeller bias | "Author-labelled" wording; external label sheets |
| A model grading its own family | Independence check, flagged rows |
| Content filters silently dropping medical items | Counted as failures |
| Prompt injection / XSS | Delimited prompts, injection chaos test, escaped HTML |
| Agent-written code drifts | import-linter, pyright strict, ruff, `make verify`, ADR `Enforced by:` |

## Out of scope for 1.0

Full text beyond abstracts; compound ranking benchmarks; multi-user hosting; hosted deployment (the image
is kept compatible).
