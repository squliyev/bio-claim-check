# ADR 0007 — Ports are base classes, backends sit beside them, and rules describe kinds

- **Status:** Accepted
- **Date:** 2026-10-20
- **Supersedes / Extends:** Extends 0002 (replaces its "ports.py / fakes.py / adapters in infrastructure" layout)
- **Related:** 0002, 0003
- **Enforced by:** `tests/arch/test_port_guards.py::test_the_real_ports_have_the_adk_shape`, `tests/arch/test_port_guards.py::test_only_backends_import_drivers`, `tests/arch/test_port_guards.py::test_importing_every_core_package_loads_no_driver`, `tests/arch/test_port_guards.py::test_leaf_packages_import_only_common`, `tests/arch/test_port_guards.py::test_contracts_import_only_common_and_leaves`, `tests/arch/test_port_guards.py::test_core_has_no_import_time_registries`, `tests/arch/test_rules_fire.py::test_no_llm_sources_are_exactly_the_marked_modules`, import-linter contracts `pure-modules-import-no-drivers`, `engine-is-feature-agnostic`, `infrastructure-holds-only-transport`, `driving-adapters-use-the-container` and `usecases-are-interface-free`, ruff `TID251` (wall clock and randomness), pyright `reportImplicitOverride`.

## Context

Up to S05 a port was a `Protocol` in the slice's `ports.py`, its test double lived in `fakes.py`, and
real adapters were meant to go in `infrastructure/`. Three problems showed up:

- "Who implements this port?" had no answer you could grep. A structural `Protocol` is satisfied by
  accident, and a misspelled method is only found when it is called.
- `infrastructure` was drifting into a second home for domain logic: the rule-pack loader and the report
  writer both imported `features`.
- Several rules named their modules one by one. Every new slice, port or deterministic module meant
  editing a rule, and a rule edited in the same change as the code it guards proves little.

Google's Agent Development Kit (`google/adk-python`, `memory/` and `sessions/`) solves the first problem neatly: one `base_<thing>.py` with an
abstract class, then one file per implementation named after its backend (`in_memory_…`, `database_…`).
We adopt that shape and adapt it to our rings.

## Decision

**1. A port is an abstract base class.**
- `base_<thing>.py` holds exactly one public class, `Base<Thing>(ABC)`, with at least one
  `@abstractmethod`. Its docstrings are the contract (Args, Returns, Raises).
- A base never imports its implementations.
- Implementations subclass the base explicitly and mark every overriding method `@override`
  (pyright `reportImplicitOverride = "error"`).
- No `Protocol` ports in `features` or `engine`, no `ports.py` or `fakes.py`, and no optional methods
  that raise `NotImplementedError`: a capability you cannot see in the type is split into its own port.

**2. Implementations are named by backend and sit beside their base.**
- `<prefix>_<thing>.py` in the base's package. `in_memory_` is a real, simple store; `scripted_` returns
  canned judgement (answerer, verifier, later the LLM client). Both are driver-free.
- Any other prefix is a **backend** (`europe_pmc_literature_source.py`, `sqlite_cache.py`). A backend
  may import drivers; nothing outside `app` imports a backend, so importing a slice never loads a driver.
- A base marked `[EXTENSION POINT]` (the pipeline processor bases, S08) may be implemented in any
  feature or engine package, named `<what>_<base stem>.py`.
- Test doubles in `tests/` subclass the base too.

**3. Infrastructure holds only generic transport.** `publish`, `strict_yaml`, `text_files`: no feature
or engine imports. Feature knowledge (parsing a rule pack, canonical report bytes) lives in its slice;
`app` composes the two.

**4. The engine is the feature-agnostic core runtime.** It never imports `features` (not even
`features.contracts`), `infrastructure` or `app`. Engine bases are generic over their payload; features
extend them; `app` wires the extensions in. If engine code needs a domain type, the type belongs in
`common` or the logic belongs in a feature.

**5. Leaves and vocabulary.** A package whose docstring declares `[LEAF]` imports only `common`
(`engine.events` is the first). `features.contracts` imports only `common` and leaf packages.

**6. No import-time registries** in `common`, `engine` or `features`: order and wiring are assembled
explicitly in `app`. The guard looks at statements that run on import, including the bodies of
top-level `if`/`try`/`with`/loops; it flags bare calls, item/attribute mutation, `regist*` calls and
`register` decorators. Plain constants (`_RE = re.compile(...)`) stay legal: a guard cannot tell every
factory from a registry, and review covers the rest.

**7. The app's driving adapters stay thin.** `app.cli` and `app.ui` reach infrastructure only through
the container; use cases receive ports and never import interfaces, the container or infrastructure.

**8. No wall clock or randomness in production code** (`datetime.now`, `time.time`, `random`,
`uuid.uuid4`, `secrets`, …). Canonical artifacts must be byte-identical; time arrives through an
injected clock (`common/base_clock.py`; amended by [ADR 0016](./0016-pipeline-events-and-clock.md): exactly
one module, `common/system_clock.py`, may read the wall clock). `uuid.uuid5` stays allowed. `importlib.import_module` is banned too, so every
import stays visible to the import rules (the builtin `__import__` is deliberate evasion and is left to
review).

**9. Rules describe kinds, never instances.** A rule names a ring, a package marker, a file-name prefix
or a docstring marker, never a list of today's modules. The single sources of truth are the folder tree,
the file-name convention, module docstrings (`[LEAF]`, `[EXTENSION POINT]`, "No LLM is involved") and the
dependency-policy table. Adding a slice, port, backend or deterministic module must pass the existing
rules **without editing them**. If it cannot, it is a new concept and needs an ADR; any session that
edits a contract or guard records why in its dev-log. Every contract and guard has a rogue and an
allowed case.

  **The two exceptions** are lists, because import-linter cannot select modules by marker: the `slices`
  contract and the sources of `no-llm-in-deterministic-code`. Parity tests derive both from the single
  source of truth (the folder tree and the "No LLM is involved" docstrings), so adding a slice or a
  deterministic module fails until the list is updated. That edit is mechanical, and it is forced.

## Consequences

- **Positive:**
  - The tree is the index of implementations, and pyright catches a missing or misspelled method.
  - Backends own their driver and their mapping code, so they are tested offline beside their base.
  - New slices and backends arrive without rule edits, so a rule change is always a visible decision.
- **Negative / costs:**
  - Nominal subclassing: a test double must inherit the base instead of just matching its shape.
  - The guards import every module under `src` to inspect classes; a module with import-time side
    effects would run them (none exist, and I28 forbids them in the core).
- **Follow-ups:**
  - S06: the first backend (Europe PMC) and the first shared contract suite; offline tests block sockets.
  - S08: processor bases in `engine/pipeline`; S11: events in `engine/events`.
  - S09 decides where the LLM SDK backends sit within this rule.
