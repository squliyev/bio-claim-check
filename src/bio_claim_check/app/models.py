"""[RING:app] Our model deployments: the facts the engine's `ModelCatalog` is built from.

Why: deployment names, providers and pinned model ids are configuration of *this* project, not engine
code (the engine owns only the shape, ADR 0012). `model_version` is the provider's pinned version as the
Foundry portal shows it (S09, ADR 0014); a deployment not yet pinned keeps its name until it is.
`family` is who trained the model (the independence flag, ADR 0019). Prices are `None` ("unpriced",
never 0) until the author copies them from the provider's pricing page with a date and source.
`max_output_tokens` for Claude is our budget (the Messages API requires one), not a
model limit. `RATER_FAMILIES` is the closed list of models allowed on a trap confirmation panel (ADR 0023):
they are not deployments (the app never calls them), but their family is looked up here, never typed.
Must not: invent a number (price, context window, token limit) or read configuration.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from bio_claim_check.common.model_family import ModelFamily
from bio_claim_check.engine.llm.model_spec import ModelCatalog, ModelSpec, Provider

MODEL_SPECS: Final = (
    ModelSpec(
        deployment="gpt-6.1-sol",
        provider=Provider.FOUNDRY_OPENAI,
        model_version="2026-09-29",
        family=ModelFamily.OPENAI,
        price=None,
    ),
    ModelSpec(
        deployment="claude-opus-4-8",
        provider=Provider.FOUNDRY_ANTHROPIC,
        model_version="claude-opus-4-8",  # Foundry shows no separate Claude version: the id is the pin
        family=ModelFamily.ANTHROPIC,
        params={"max_output_tokens": 8192},
        price=None,
    ),
    ModelSpec(
        deployment="Kimi-K2.6-1",
        provider=Provider.FOUNDRY_OPENAI,
        model_version="Kimi-K2.6-1",
        family=ModelFamily.MOONSHOT,
        price=None,
    ),
)


def model_catalog() -> ModelCatalog:
    """The catalogue of every deployment a run may use."""
    return ModelCatalog(MODEL_SPECS)


RATER_FAMILIES: Final[Mapping[str, ModelFamily]] = MappingProxyType(
    {"gemini-4-argon": ModelFamily.GOOGLE, "grok-4.7": ModelFamily.XAI}
)
"""Panel raters and who trained them; a rater not listed here is refused (ADR 0023, I79)."""
