"""`common.canonical_json` must give exactly the bytes of the inline copies it replaced.

The oracles below are the `json.dumps` expressions that lived in corpus `serialise`, report `canonical`,
the cache key and the prompt hash before S08b, written out verbatim. If either variant drifts, every
sealed hash, golden file and cache key would silently change, so these tests pin them (I48).
"""

import hashlib
import json
import math
from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from bio_claim_check.common.canonical_json import compact_json, compact_sha256, pretty_json, pretty_json_bytes

pytestmark = pytest.mark.unit

SAMPLES: list[object] = [
    {},
    [],
    None,
    True,
    0,
    10**30,
    "é β ü \u2009 \U0001f9ec",
    {"z": [1, {"é": "β ü", "a": None}], "a": True, "s": "0.10", "e": {}, "l": []},
    [{"b": 1, "a": 2}, {"a": [3, 1]}],
    {"nested": {"y": {"x": {"w": "deep"}}}, "quote": 'he said "no"\n'},
]


def _old_compact(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _old_pretty_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()


@pytest.mark.parametrize("value", SAMPLES)
def test_compact_matches_the_replaced_expression(value: object) -> None:
    assert compact_json(value) == _old_compact(value)
    assert compact_sha256(value) == hashlib.sha256(_old_compact(value).encode("utf-8")).hexdigest()


@pytest.mark.parametrize("value", SAMPLES)
def test_pretty_matches_the_replaced_expression(value: object) -> None:
    assert pretty_json_bytes(value) == _old_pretty_bytes(value)
    assert pretty_json(value) + "\n" == pretty_json_bytes(value).decode("utf-8")
    assert not pretty_json(value).endswith("\n")


json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=5), inner, max_size=4),
    max_leaves=20,
)


@given(json_values)
def test_both_variants_match_the_oracles_on_any_json(value: object) -> None:
    assert compact_json(value) == _old_compact(value)
    assert pretty_json_bytes(value) == _old_pretty_bytes(value)


def test_key_order_does_not_matter() -> None:
    assert compact_json({"b": 1, "a": 2}) == compact_json({"a": 2, "b": 1}) == '{"a":2,"b":1}'


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, {"x": [math.nan]}])
@pytest.mark.parametrize("serialise", [compact_json, pretty_json, pretty_json_bytes, compact_sha256])
def test_nan_and_infinity_are_refused(bad: object, serialise: Callable[[object], object]) -> None:
    with pytest.raises(ValueError, match="JSON compliant"):
        serialise(bad)
