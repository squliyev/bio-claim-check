"""[RING:common] Who trained a model, as a closed vocabulary shared by the model catalogue and the report.

Why: the independence flag (`same_family`, ADR 0019) compares families, not providers (Kimi is served by an
OpenAI-compatible endpoint but is not an OpenAI model). It lives here, not in `engine.llm`, so the report,
which must not import LLM code, validates a stored family against the same enum the catalogue uses.
Must not: grow a family without a deployment or a panel rater that needs it (raters: ADR 0023).

No LLM is involved in this module.
"""

from enum import StrEnum


class ModelFamily(StrEnum):
    """Who trained a model."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    MOONSHOT = "moonshot"
    GOOGLE = "google"
    XAI = "xai"
