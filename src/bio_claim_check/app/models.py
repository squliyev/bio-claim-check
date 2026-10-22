"""[RING:app] Our model deployments: the facts the engine's `ModelCatalog` is built from.

Why: deployment names, providers and pinned model ids are configuration of *this* project, not engine
code (the engine owns only the shape, ADR 0012). `model_version` is the provider's pinned version as the
Foundry portal shows it (S09, ADR 0014); a deployment not yet pinned keeps its name until it is. Prices
are `None` ("unpriced", never 0) until the author copies them from the provider's pricing page with a
date and source. `max_output_tokens` for Claude is our budget (the Messages API requires one), not a
model limit.
Must not: invent a number (price, context window, token limit) or read configuration.
"""

from typing import Final

from bio_claim_check.engine.llm.model_spec import ModelCatalog, ModelSpec, Provider

MODEL_SPECS: Final = (
    ModelSpec(
        deployment="gpt-6.1-sol", provider=Provider.FOUNDRY_OPENAI, model_version="2026-09-29", price=None
    ),
    ModelSpec(
        deployment="claude-opus-4-8",
        provider=Provider.FOUNDRY_ANTHROPIC,
        model_version="claude-opus-4-8",  # BLOCKING (S09): pin from the Foundry portal before the S09 commit
        params={"max_output_tokens": 8192},
        price=None,
    ),
    ModelSpec(
        deployment="Kimi-K2.6-1", provider=Provider.FOUNDRY_OPENAI, model_version="Kimi-K2.6-1", price=None
    ),
)


def model_catalog() -> ModelCatalog:
    """The catalogue of every deployment a run may use."""
    return ModelCatalog(MODEL_SPECS)
