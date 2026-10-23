"""Model wiring (S08): each role resolves through the catalogue and checks its provider (I46)."""

from typing import Any

import pytest
from tests.support.settings import make_settings

from bio_claim_check.app.container import MissingProviderError, build_models
from bio_claim_check.app.models import MODEL_SPECS, model_catalog
from bio_claim_check.app.settings import Settings
from bio_claim_check.common.model_family import ModelFamily
from bio_claim_check.engine.llm.model_spec import (
    ModelCatalog,
    ModelSpec,
    Provider,
    UnknownDeploymentError,
)

pytestmark = pytest.mark.unit

FOUNDRY = {"base_url": "https://example.org/", "api_key": "test-key"}


def settings(**values: Any) -> Settings:
    return make_settings(**values)


def test_the_shipped_catalogue_is_unpriced_and_names_the_default_roles() -> None:
    catalog = model_catalog()
    assert all(spec.price is None for spec in MODEL_SPECS), "no price may be invented"
    defaults = settings()
    for deployment in (defaults.answer_model, defaults.verifier_model, defaults.trap_model):
        assert catalog.lookup(deployment).deployment == deployment


def test_roles_resolve_when_their_provider_is_configured() -> None:
    roles = build_models(settings(foundry=FOUNDRY), model_catalog())
    assert (roles.answer.deployment, roles.verifier.deployment, roles.trap.deployment) == (
        "gpt-6.1-sol",
        "claude-opus-4-8",
        "Kimi-K2.6-1",
    )


@pytest.mark.parametrize("mode", ["read-write", "off"])
def test_a_live_role_without_provider_settings_fails_naming_the_role(mode: str) -> None:
    with pytest.raises(MissingProviderError, match=r"the answer model 'gpt-6\.1-sol' needs foundry"):
        build_models(settings(cache_mode=mode), model_catalog())


def test_only_the_role_whose_provider_is_missing_is_named() -> None:
    catalog = ModelCatalog(
        [
            *MODEL_SPECS,
            ModelSpec(
                deployment="local",
                provider=Provider.OLLAMA,
                model_version="m@sha256:0",
                family=ModelFamily.OPENAI,
                price=None,
            ),
        ]
    )
    with pytest.raises(
        MissingProviderError, match=r"the trap model 'local' needs ollama settings \(BCC_OLLAMA__\*\)"
    ):
        build_models(settings(foundry=FOUNDRY, trap_model="local"), catalog)


def test_a_read_only_replay_needs_no_provider() -> None:
    roles = build_models(settings(cache_mode="read-only"), model_catalog())
    assert roles.verifier.provider is Provider.FOUNDRY_ANTHROPIC


def test_an_unknown_deployment_fails_at_wiring_even_in_read_only() -> None:
    with pytest.raises(UnknownDeploymentError, match="'gpt-typo'"):
        build_models(settings(cache_mode="read-only", answer_model="gpt-typo"), model_catalog())


def test_every_deployment_names_who_trained_it() -> None:
    """The independence flag (ADR 0019): the family is the trainer, not the serving API."""
    assert {spec.deployment: spec.family for spec in MODEL_SPECS} == {
        "gpt-6.1-sol": ModelFamily.OPENAI,
        "claude-opus-4-8": ModelFamily.ANTHROPIC,
        "Kimi-K2.6-1": ModelFamily.MOONSHOT,
    }
