"""[RING:engine/prompts] A prompt template whose identity is its text, rendered without surprises.

Why: every manifest and LLM call record names the exact prompt that produced it (`PromptRef`), so the
hash must come from the text itself, never from a hand-maintained version string alone. Rendering is
strict in both directions: a placeholder without a value and a value without a placeholder are both
errors, because either one means the template and its caller drifted apart (the prompt/parser coupling
hazard). `string.Template` substitutes once, so a `$name` inside a value (an abstract can contain `$`)
is never expanded again.
Must not: hold domain prompt text, read files, or fall back to a default for a missing value.

Pure values: makes no provider call. (It is LLM vocabulary, so it does not carry the
ADR 0003 deterministic marker.)
"""

import hashlib
import json
from collections.abc import Mapping
from string import Template
from typing import Annotated, Self

from pydantic import Field, model_validator

from bio_claim_check.common.models import NonBlankStr, ValidatedModel
from bio_claim_check.engine.llm.messages import Message, PromptRef


class PromptRenderError(ValueError):
    """The variables do not match the template's placeholders exactly."""


class PromptTemplate(ValidatedModel):
    name: NonBlankStr
    version: Annotated[int, Field(strict=True, ge=1)]
    system: NonBlankStr
    user: NonBlankStr

    @model_validator(mode="after")
    def _valid_placeholders(self) -> Self:
        for part in ("system", "user"):
            if not Template(getattr(self, part)).is_valid():
                raise ValueError(f"{part}: invalid placeholder (use $name or ${{name}}; a literal $ is $$)")
        return self

    @property
    def placeholders(self) -> frozenset[str]:
        return frozenset(Template(self.system).get_identifiers() + Template(self.user).get_identifiers())

    @property
    def sha256(self) -> str:
        """Of the canonical JSON of every field, so any change to the text changes the hash."""
        body = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def ref(self) -> PromptRef:
        return PromptRef(name=self.name, version=self.version, sha256=self.sha256)


def render(template: PromptTemplate, variables: Mapping[str, str]) -> tuple[Message, Message]:
    """The system and user messages; raises `PromptRenderError` naming missing and extra variables."""
    missing = sorted(template.placeholders - variables.keys())
    extra = sorted(variables.keys() - template.placeholders)
    if missing or extra:
        raise PromptRenderError(f"{template.name} v{template.version}: missing {missing}, extra {extra}")
    return (
        Message(role="system", content=Template(template.system).substitute(variables)),
        Message(role="user", content=Template(template.user).substitute(variables)),
    )
