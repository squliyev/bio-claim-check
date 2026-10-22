"""[RING:engine/pipeline] Tiny abstract bases for request and response processors (S08).

Why: LLM-side behaviour (prompt rendering, structured output, usage, context isolation, evidence) is a
chain of small processors, each living in the package that understands it. The bases here are
`[EXTENSION POINT]`s: any feature or engine package may implement them, named
`<what>_<base stem>.py`. The chain's order is assembled in `app`, never by registration.
Must not: import features (contract `engine-is-feature-agnostic`); bases are generic over their payload.
Contents (S08): `Invocation` (domain payload vs the request a provider sees), the two bases, and
`LlmRunner`, which owns the order: request processors, schema, call, spend, finish reason, validation
with at most one repair, then typed response processors (ADR 0012).
"""
