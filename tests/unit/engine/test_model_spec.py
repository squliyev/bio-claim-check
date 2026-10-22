"""The catalogue fails fast (I46) and a spec's identity is what keys the cache."""

import pytest
from pydantic import ValidationError
from tests.support.llm import spec

from bio_claim_check.engine.llm.model_spec import ModelCatalog, ModelSpec, UnknownDeploymentError

pytestmark = pytest.mark.unit


def test_lookup_returns_the_spec() -> None:
    catalog = ModelCatalog([spec("a"), spec("b")])
    assert catalog.lookup("b") == spec("b")
    assert [s.deployment for s in catalog] == ["a", "b"]


def test_unknown_deployment_names_what_is_known() -> None:
    with pytest.raises(UnknownDeploymentError, match=r"'c'.*known: a, b") as caught:
        ModelCatalog([spec("b"), spec("a")]).lookup("c")
    assert caught.value.deployment == "c"


def test_duplicate_deployment_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"listed twice"):
        ModelCatalog([spec("a"), spec("a")])


def test_identity_carries_provider_deployment_and_version() -> None:
    identity = spec("a").identity()
    assert (identity.provider, identity.deployment, identity.model_version) == (
        spec().provider,
        "a",
        "a-v1",
    )


@pytest.mark.parametrize("field", ["deployment", "model_version"])
def test_blank_names_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        ModelSpec.model_validate({**spec().model_dump(), field: " "})


def test_params_are_deeply_immutable() -> None:
    params = spec().params
    with pytest.raises(TypeError):
        params["temperature"] = 1  # type: ignore[index]  # proving the mapping is read-only
    with pytest.raises(TypeError):
        params["nested"]["top_p"] = 0  # type: ignore[index]  # proving nested mappings are read-only too
