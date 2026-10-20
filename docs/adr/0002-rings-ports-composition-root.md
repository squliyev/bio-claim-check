# ADR 0002 — Rings, slices, ports and a composition root

- **Status:** Accepted
- **Date:** 2026-10-20
- **Supersedes / Extends:** — (extended by 0007: port shape, backend placement, transport-only infrastructure)
- **Related:** 0001, 0003, 0007
- **Enforced by:** import-linter contracts `rings`, `slices`, `contracts-do-not-depend-on-slices`, `no-cycles`, `pure-modules-import-no-drivers` and `engine-is-feature-agnostic`, plus `tests/arch/test_guards.py::test_the_real_package_has_no_ancestor_imports`, proven by `tests/arch/test_rules_fire.py` · ruff `TID251` ban on `tests` in `src/` · `tests/arch/test_guards.py::test_every_source_module_has_a_correct_ring_header`

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
| `engine` | the **feature-agnostic** core runtime and its generic ports (LLM client, cache, ledger, clock) | `common` (never `features`, not even `features.contracts`) |
| `features` | domain, one **vertical slice** per sub-package; each port's backends sit beside its base (ADR 0007) | `engine`, `common` |
| `infrastructure` | tiny, generic, feature-agnostic transport (atomic publish, strict YAML, reading text files) | `common` only |
| `app` | settings, composition root (`container`), use cases, CLI, UI | everything |

**Slices.** The slices are `retrieval`, `answer`, `checks`, `verify`, `baselines`, `traps`, `report`,
`bench` and `annotate`.
- They are mutually independent.
- They share vocabulary only through `features.contracts`, which itself imports no slice.
- Work that combines slices lives in `app.usecases`.

**Drivers stay at the edges.** Pure modules (`common`, `engine.events`, `features.contracts`,
`features.checks`, `features.report`, `bench.stats`, `annotate.agreement`) never import the listed
driver modules (`httpx`, `openai`, `anthropic`, `tenacity`, `sqlite3`, `streamlit`, `typer`,
`pydantic_settings`, `yaml`). Elsewhere in the core only **backend modules** may import a driver
(ADR 0007); `infrastructure` and `app` may too. Every direct runtime dependency is classified as `core`
or `driver` in `tests/arch/test_dependency_policy.py`,
so a new SDK cannot arrive without a deliberate, reviewed classification. The list is a deny-list,
not a detector of every possible driver. The rule sees direct imports and imports through our own
modules; it does not inspect the internals of allowed third-party packages.

**No import cycles** in the statically detected import graph (dynamic `importlib` loading is out of
scope). Sibling modules are acyclic at every depth (`no-cycles`). That contract cannot
see a package `__init__` that re-exports from a child which imports the package back, so a guard also
forbids any module from importing its own ancestor package (the root package is exempt as a target
and must itself import nothing internal).

**Ports belong to their consumer.** A domain port (for example `BaseLiteratureSource`, `BaseVerifier`)
is declared by the slice that *uses* it, as an abstract base class in `base_<thing>.py`; its
implementations sit beside it, named by backend (ADR 0007). Only `app` wires the concrete class in.
Generic, domain-free ports live in `engine`.

**Slice layout.** Files are created only when needed, in this order:
1. `base_<thing>.py` (the port).
2. `models.py`.
3. Capability modules (pure logic).
4. `in_memory_<thing>.py` or `scripted_<thing>.py` (driver-free implementations used by the demo,
   tests and shared contract suites).
5. A shared contract suite in `tests/contract/`.
6. Only then a backend, `<backend>_<thing>.py`, beside the base.

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
  - Built in S05: `app/container.py` (the only place concrete classes meet) and `app/usecases/run.py`
    (the first code that combines slices).
  - The first backends in S06 (Europe PMC) and S08–S09 (LLM).
