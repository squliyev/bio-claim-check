"""[RING:app] Our model deployments: the facts the engine's `ModelCatalog` is built from.

Why: deployment names, providers and pinned model ids are configuration of *this* project, not engine
code (the engine owns only the shape, ADR 0012). `model_version` equals the deployment name until S09's
live ping records the provider's own model id; prices are `None` ("unpriced", never 0) until the author
copies them from the provider's pricing page with a date and source.
Must not: invent a number (price, context window, token limit) or read configuration.
"""

from typing import Final

from bio_claim_check.engine.llm.model_spec import ModelCatalog, ModelSpec, Provider

MODEL_SPECS: Final = (
    ModelSpec(
        deployment="gpt-6.1-sol", provider=Provider.FOUNDRY_OPENAI, model_version="gpt-6.1-sol", price=None
    ),
    ModelSpec(
        deployment="claude-opus-4-8",
        provider=Provider.FOUNDRY_ANTHROPIC,
        model_version="claude-opus-4-8",
        price=None,
    ),
    ModelSpec(
        deployment="Kimi-K2.6-1", provider=Provider.FOUNDRY_OPENAI, model_version="Kimi-K2.6-1", price=None
    ),
)


def model_catalog() -> ModelCatalog:
    """The catalogue of every deployment a run may use."""
    return ModelCatalog(MODEL_SPECS)
