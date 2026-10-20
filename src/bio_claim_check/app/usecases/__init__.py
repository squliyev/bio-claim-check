"""[RING:app/usecases] Use cases: the code that combines feature slices into one flow.

Why: slices never import each other (ADR 0002), so orchestration lives here, above them. Interfaces
(CLI, UI) call a use case and render its result; they hold no flow of their own.
Must not: do I/O directly or choose adapters (the container does).
"""
