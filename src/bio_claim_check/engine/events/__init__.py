"""[RING:engine/events] [LEAF] The pipeline event vocabulary: a base event and the generic events.

Why: every run will emit typed events (stage, LLM call, usage, failure) into `events.jsonl` (S11).
Domain events (e.g. a verdict produced) subclass the base in `features.contracts`; the closed union is
assembled in `app`, so this package never needs a domain type.
Must not: import anything from this project except `common` (`[LEAF]` guard), or carry canonical data:
events may hold volatile values (time from an injected clock), canonical artifacts never do.
Empty until S11; the boundary exists now so its rules are in force before code lands.

No LLM is involved in this package.
"""
