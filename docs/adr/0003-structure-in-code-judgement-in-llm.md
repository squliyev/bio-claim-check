# ADR 0003 — Structure in code, judgement in the LLM

- **Status:** Accepted
- **Date:** 2026-10-20
- **Supersedes / Extends:** —
- **Related:** 0002, 0004
- **Enforced by:** import-linter contract `no-llm-in-deterministic-code`, proven by `tests/arch/test_rules_fire.py`

## Context

An LLM is useful for *judgement*: does this claim overstate the abstract? It is a liability for
*structure*: does this quote occur in the abstract, how many items were flagged, what is the confidence
interval? A model asked to do bookkeeping can be confidently wrong, and the error then sits inside the
numbers we publish.

## Decision

- Anything that can be decided by code **is** decided by code, deterministically and with tests.
  Examples: quote location, citation checks, durable run state, scoring, statistics and agreement.
- The LLM is called only where judgement is required (answering and verifying), and its output is a
  validated, schema-bound object, never free prose that code later parses.
- **What code verifies is kept apart from what the model judged** (two axes in every verdict; S04).
- The modules that must stay deterministic say so in their docstring ("No LLM is involved in this
  module"). They are forbidden from importing `engine.llm`:
  - `features.checks`
  - `features.bench.stats`
  - `features.annotate.agreement`

## Consequences

- **Positive:**
  - The numbers in tables are reproducible to the last digit.
  - A wrong model output cannot silently become a wrong statistic.
- **Negative / costs:**
  - Some checks a model could do "well enough" must be written and tested by hand.
- **Follow-ups:**
  - Add new deterministic modules to the contract when they are created.
