# Invariants

The rules this project must never break. Each one has a **static guard**, which is fast and catches the
mistake early, and a **semantic test**, which proves the guard actually fires.

**A new invariant MUST be added to this table** together with its guard and test. Every reference here
is checked by `tests/arch/test_project_files.py::test_every_invariant_reference_resolves`.

Reference kinds:
- `import-linter:<contract id>`
- `ruff:<rule>`
- `pytest:<file>::<test>`
- `ci:<job>`

| id | Invariant | Static guard | Semantic test |
|----|-----------|--------------|---------------|
| I1 | Rings point inward (ADR 0002) | import-linter:rings | pytest:tests/arch/test_rules_fire.py::test_contract_fires_only_on_rogue_imports |
| I2 | Feature slices are independent; only `features.contracts` is shared (ADR 0002) | import-linter:slices | pytest:tests/arch/test_rules_fire.py::test_slices_contract_lists_every_feature_package |
| I3 | `features.contracts` imports no slice (ADR 0002) | import-linter:contracts-do-not-depend-on-slices | pytest:tests/arch/test_rules_fire.py::test_shared_contracts_forbid_every_slice |
| I4 | Deterministic modules never import the LLM engine (ADR 0003) | import-linter:no-llm-in-deterministic-code | pytest:tests/arch/test_rules_fire.py::test_deterministic_contract_sources_are_all_exercised |
| I5 | Only `app.settings` reads the environment (ADR 0001) | ruff:TID251 | pytest:tests/arch/test_ruff_bans.py::test_env_access_banned_outside_settings |
| I6 | Production code never imports test support (ADR 0002) | ruff:TID251 | pytest:tests/arch/test_ruff_bans.py::test_src_cannot_import_tests |
| I7 | Every source module declares its ring (ADR 0002) | pytest:tests/arch/test_guards.py::test_every_source_module_has_a_correct_ring_header | pytest:tests/arch/test_guards.py::test_ring_header_rejects |
| I8 | Every ADR states how it is enforced | pytest:tests/arch/test_guards.py::test_every_adr_has_status_date_and_enforced_by | pytest:tests/arch/test_guards.py::test_adr_fields_rejects |
| I9 | Secrets are never rendered (ADR 0001) | pytest:tests/unit/app/test_settings.py::test_secrets_never_render | pytest:tests/unit/app/test_cli.py::test_config_redacts_secrets |
| I10 | No secrets or real endpoints in git history (ADR 0001) | ci:secrets | ci:secrets |
