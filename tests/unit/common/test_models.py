"""Shared validated models and value types (common/models.py)."""

from types import MappingProxyType

import pytest
from pydantic import Field, JsonValue, ValidationError

from bio_claim_check.common.models import FrozenJson, NonBlankStr, Sha256Hex, ValidatedModel, thaw


class _Holder(ValidatedModel):
    name: NonBlankStr
    digest: Sha256Hex | None = None
    data: FrozenJson = Field(default_factory=dict)


def test_non_blank_rejects_whitespace_and_non_strings() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        _Holder(name="  ")
    with pytest.raises(ValidationError):
        _Holder.model_validate({"name": 1})


@pytest.mark.parametrize("digest", ["A" * 64, "a" * 63, "g" * 64])
def test_sha256_hex_rejects_wrong_shape(digest: str) -> None:
    with pytest.raises(ValidationError):
        _Holder(name="x", digest=digest)


def test_validated_model_is_frozen_and_refuses_unvalidated_copies() -> None:
    holder = _Holder(name="x")
    with pytest.raises(ValidationError):
        holder.name = "y"
    with pytest.raises(TypeError, match=r"validated on construction; build a new one$"):
        holder.model_copy(update={"name": "y"})
    assert holder.model_copy() == holder
    with pytest.raises(ValidationError):
        _Holder.model_validate({"name": "x", "extra": 1})


def test_frozen_json_is_read_only_all_the_way_down() -> None:
    source: dict[str, JsonValue] = {"a": {"b": [1, {"c": 2}]}, "d": "e"}
    holder = _Holder(name="x", data=source)
    source["d"] = "changed"
    assert holder.data["d"] == "e"
    inner = holder.data["a"]
    assert isinstance(inner, MappingProxyType)
    nested = inner["b"]
    assert nested == (1, MappingProxyType({"c": 2}))
    with pytest.raises(TypeError):
        inner["b"] = 1


def test_frozen_json_dumps_as_plain_json_and_round_trips() -> None:
    holder = _Holder(name="x", data={"a": [1, {"b": None}], "c": 1.5})
    dumped = holder.model_dump(mode="json")
    assert dumped["data"] == {"a": [1, {"b": None}], "c": 1.5}
    assert type(holder.model_dump()["data"]) is dict
    assert _Holder.model_validate_json(holder.model_dump_json()) == holder
    assert _Holder(name="x", data=holder.data) == holder


def test_frozen_json_rejects_non_json_values() -> None:
    with pytest.raises(ValidationError):
        _Holder(name="x", data={"a": object()})  # pyright: ignore[reportArgumentType] - non-JSON on purpose


@pytest.mark.parametrize("data", [{1: "a"}, {1: "a", "1": "b"}, {"x": {2: "nested"}}])
def test_frozen_json_rejects_non_string_keys_instead_of_merging_them(data: dict[object, str]) -> None:
    with pytest.raises(ValidationError, match="keys must be strings"):
        _Holder(name="x", data=data)  # pyright: ignore[reportArgumentType] - non-string keys on purpose


def test_thaw_passes_plain_values_through() -> None:
    assert thaw(MappingProxyType({"a": (1, 2)})) == {"a": [1, 2]}
    assert thaw("s") == "s"
    assert thaw(None) is None
