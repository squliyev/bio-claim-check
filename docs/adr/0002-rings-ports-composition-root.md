# ADR 0002 — Rings, slices, ports and a composition root

- **Status:** Accepted
- **Date:** 2026-10-20
- **Supersedes / Extends:** —
- **Related:** 0001, 0003
- **Enforced by:** import-linter contracts `rings`, `slices` and `contracts-do-not-depend-on-slices`, proven by `tests/arch/test_rules_fire.py` · ruff `TID251` ban on `tests` in `src/` · `tests/arch/test_guards.py::test_every_source_module_has_a_correct_ring_header`

## Context

The pipeline has deterministic parts (quote location, statistics) and judgement parts (an LLM
answering and verifying). It also has swappable edges: literature sources, LLM providers and storage.
Without enforced boundaries, provider details leak into domain logic, and tests need the network. Most
code here is written with coding agents, so boundaries that live only in prose will erode.

## Decision

The package is arranged in **rings that point inward**:

```
app ─► infrastructure ─► features ─► engine ─► common
```

| Ring | Holds | May import |
|---|---|---|
| `common` | errors, ids, text primitives | nothing in the package |
| `engine` | generic runtime and **generic ports** (`LlmClient`, cache, ledger, clock) | `common` |
| `features` | pure domain, one **vertical slice** per sub-package | `engine`, `common` |
| `infrastructure` | adapters (Europe PMC, providers, SQLite, filesystem) | everything inward |
| `app` | settings, composition root (`container`), use cases, CLI, UI | everything |

**Slices.** The slices are `retrieval`, `answer`, `checks`, `verify`, `baselines`, `traps`, `report`,
`bench` and `annotate`.
- They are mutually independent.
- They share vocabulary only through `features.contracts`, which itself imports no slice.
- Work that combines slices lives in `app.usecases`.

**Ports belong to their consumer.** A domain port (for example `LiteratureSource`, `Verifier`) is
declared by the slice that *uses* it, in that slice's `ports.py`. `infrastructure` implements it, and
only `app` wires the concrete class in. Generic, domain-free ports live in `engine`.

**Slice layout.** Files are created only when needed, in this order:
1. `ports.py` (interfaces).
2. `models.py`.
3. Capability modules (pure logic).
4. `fakes.py` (in-memory implementations used by tests and shared contract suites).

A real adapter is added only after its port, fake and contract suite exist.

**Module headers.** Every module's docstring starts with `[RING:<ring>]` or `[RING:<ring>/<slice>]` and
explains why it exists and what it must not do. Test support lives in `tests/support/`, is tagged
`[TEST SUPPORT]`, and is never imported by production code.

## Consequences

- **Positive:**
  - Domain logic is testable without the network.
  - Providers are swappable.
  - Architecture drift fails CI with a named contract.
- **Negative / costs:**
  - Some code that could be a direct call goes through a port and a container.
  - New slices must be added to the `slices` contract; a parity test fails until they are.
- **Follow-ups:**
  - `app/container.py` in S05.
  - The first real ports in S06 and S08.
