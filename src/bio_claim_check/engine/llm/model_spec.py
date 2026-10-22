"""[RING:engine/llm] Model specs and the catalogue that fails fast on an unknown deployment.

Why: a typo'd or retired deployment name must stop the run at wiring, not after half a benchmark (R8).
The engine owns the shape; the concrete deployments (and prices) are app data (`app/models.py`).
`model_version` is the provider's pinned model id: the same deployment name re-pointed at another model
must not replay the old model's answers, so it is part of the LLM cache key.
Must not: hold deployment facts, default a missing field, or read configuration.

Pure values: makes no provider call. (It is LLM vocabulary, so it does not carry the
ADR 0003 deterministic marker.)
"""

from collections.abc import Iterable, Iterator
from enum import StrEnum

from pydantic import Field

from bio_claim_check.common.errors import BccError
from bio_claim_check.common.models import FrozenJson, NonBlankStr, ValidatedModel
from bio_claim_check.engine.llm.usage import Price


class Provider(StrEnum):
    """Which API serves a deployment (the S09 adapter is chosen by this)."""

    FOUNDRY_OPENAI = "foundry_openai"
    FOUNDRY_ANTHROPIC = "foundry_anthropic"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


class ModelIdentity(ValidatedModel):
    """Exactly which model answered: part of every LLM cache key."""

    provider: Provider
    deployment: NonBlankStr
    model_version: NonBlankStr


class ModelSpec(ValidatedModel):
    """One deployment: who serves it, which model it is, its default parameters and its price (if known)."""

    deployment: NonBlankStr
    provider: Provider
    model_version: NonBlankStr
    params: FrozenJson = Field(default_factory=dict, validate_default=True)
    price: Price | None

    def identity(self) -> ModelIdentity:
        return ModelIdentity(
            provider=self.provider, deployment=self.deployment, model_version=self.model_version
        )


class UnknownDeploymentError(BccError, LookupError):
    """A deployment name that is not in the catalogue."""

    code = "llm.unknown_deployment"

    def __init__(self, deployment: str, known: Iterable[str]) -> None:
        super().__init__(f"unknown deployment {deployment!r}; known: {', '.join(sorted(known))}")
        self.deployment = deployment


class ModelCatalog:
    """The deployments a run may use; `lookup` raises instead of guessing."""

    def __init__(self, specs: Iterable[ModelSpec]) -> None:
        self._specs: dict[str, ModelSpec] = {}
        for spec in specs:
            if spec.deployment in self._specs:
                raise ValueError(f"deployment {spec.deployment!r} is listed twice")
            self._specs[spec.deployment] = spec

    def lookup(self, deployment: str) -> ModelSpec:
        try:
            return self._specs[deployment]
        except KeyError:
            raise UnknownDeploymentError(deployment, self._specs) from None

    def __iter__(self) -> Iterator[ModelSpec]:
        return iter(self._specs.values())
