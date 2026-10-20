"""[RING:engine/pipeline] Tiny abstract bases for request and response processors (S08).

Why: LLM-side behaviour (prompt rendering, structured output, usage, context isolation, evidence) is a
chain of small processors, each living in the package that understands it. The bases here are
`[EXTENSION POINT]`s: any feature or engine package may implement them, named
`<what>_<base stem>.py`. The chain's order is assembled in `app`, never by registration.
Must not: import features (contract `engine-is-feature-agnostic`); bases are generic over their payload.
Empty until S08; the boundary exists now so its rules are in force before code lands.
"""
