"""[RING:engine/events] The base every pipeline event extends, and the model reference events carry.

Why: one frozen, validated shape with a `type` discriminator lets `app` assemble a closed union that
consumers (the S11 writer, the S17 UI) validate against. `at` comes from the caller's injected clock via
`EventEmitter`, never from the wall clock. `ModelRef` mirrors `engine.llm.ModelIdentity` with
primitives, because this leaf may import only `common`.
Must not: hold content (text, payloads, output) or anything canonical.

No LLM is involved in this module.
"""

from typing import Any

from pydantic import AwareDatetime

from bio_claim_check.common.models import NonBlankStr, ValidatedModel


class PipelineEvent(ValidatedModel):
    """A concrete event narrows `type` to one `Literal` that is unique across the union (I58).

    `Any` here (not `str`) because a field override must keep its declared type: `Any` is the one base
    type a `Literal` may narrow; a test checks every concrete event declares a string `Literal`.
    """

    type: Any
    at: AwareDatetime


class ModelRef(ValidatedModel):
    """Which model an LLM event is about: provider, deployment and pinned version (primitives only)."""

    provider: NonBlankStr
    deployment: NonBlankStr
    model_version: NonBlankStr
