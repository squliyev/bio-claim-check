"""[RING:common] Validated model base and the small value types every ring shares.

Why: the engine (S08: LLM requests, prices, model specs) needs the same frozen, validated models and
non-blank or hash strings that the domain contracts already used. They lived in
`features.contracts`, which the engine may not import (ADR 0002), so they moved here unchanged.
`FrozenJson` is new: a JSON object that is read-only all the way down, so a value that has been hashed
into a cache key cannot be mutated afterwards.
Must not: hold domain vocabulary (labels, verdicts, papers) or perform I/O.

No LLM is involved in this module.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any, ClassVar, Self, cast, override

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    PlainSerializer,
    StringConstraints,
)


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


NonBlankStr = Annotated[str, Field(strict=True), AfterValidator(_non_blank)]
"""A string with at least one non-space character. A validator, not ``minLength``: strict-mode subset."""

Sha256Hex = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
"""A lower-case hex sha256 digest."""


class ValidatedModel(BaseModel):
    """Frozen, extra=forbid, no unvalidated copies (pydantic's `model_copy(update=...)` skips validation)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _rebuild_hint: ClassVar[str] = "build a new one"

    @override
    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        if update:
            raise TypeError(f"{type(self).__name__} is validated on construction; {self._rebuild_hint}")
        return super().model_copy(deep=deep)


def thaw(value: object) -> JsonValue:
    """A plain JSON value (dicts and lists) from a frozen one; plain values pass through."""
    if isinstance(value, Mapping):
        items = cast(Mapping[object, object], value).items()
        if bad := [key for key, _ in items if not isinstance(key, str)]:
            # ValueError so pydantic reports it; coercing would merge keys like 1 and "1"
            raise ValueError(f"JSON object keys must be strings, got {bad!r}")
        return {cast(str, key): thaw(item) for key, item in items}
    if isinstance(value, list | tuple):
        return [thaw(item) for item in cast(list[object] | tuple[object, ...], value)]
    return cast(JsonValue, value)


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        items = cast(Mapping[str, object], value).items()
        return MappingProxyType({key: _freeze(item) for key, item in items})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in cast(list[object], value))
    return value


def _freeze_object(value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    return cast(Mapping[str, JsonValue], _freeze(value))


def _thaw_object(value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], thaw(value))


FrozenJson = Annotated[
    Mapping[str, JsonValue],
    BeforeValidator(thaw),
    AfterValidator(_freeze_object),
    PlainSerializer(_thaw_object, return_type=dict[str, JsonValue]),
]
"""A JSON object frozen all the way down (mappings read-only, arrays as tuples); dumps as plain JSON."""
