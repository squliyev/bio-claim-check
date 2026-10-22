"""[RING:engine/events] [LEAF] The pipeline event vocabulary: a base event and the generic events.

Why: every LLM call must be observable from its first live run (S09): which agent, which model, which
attempt, what it cost, how it ended. Generic events live here (stage, LLM call, retry, failure); domain
events (e.g. a verdict produced) subclass `PipelineEvent` in `features.contracts`; the closed union is
assembled in `app` (ADR 0016), so this package never needs a domain or engine type.
Must not: import anything from this project except `common` (`[LEAF]` guard); carry message text,
payloads, prompt variables, model output, endpoints or keys (I59); or carry canonical data: events hold
volatile values (time from an injected clock), canonical artifacts never do. The `events.jsonl` writer
and run-level events are S11. No re-exports here: import each module directly.

No LLM is involved in this package.
"""
