"""Wilson interval against Newcombe (1998) Table I reference values, plus its input checks."""

import pytest

from bio_claim_check.features.bench.stats import wilson

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("k", "n", "lower", "upper"),
    [
        (81, 263, 0.2553, 0.3662),
        (15, 148, 0.0624, 0.1605),
        (0, 20, 0.0000, 0.1611),
        (1, 29, 0.0061, 0.1718),
    ],
)
def test_matches_newcombe_1998_table_1(k: int, n: int, lower: float, upper: float) -> None:
    assert wilson(k, n) == pytest.approx((lower, upper), abs=5e-5)


def test_all_successes_mirror_no_successes() -> None:
    lo, hi = wilson(0, 20)
    assert wilson(20, 20) == pytest.approx((1 - hi, 1 - lo))
    assert wilson(20, 20)[1] == 1.0


def test_a_wider_z_gives_a_wider_interval() -> None:
    narrow, wide = wilson(5, 10, z=1.0), wilson(5, 10)
    assert wide[0] < narrow[0]
    assert narrow[1] < wide[1]


@pytest.mark.parametrize(
    ("k", "n", "z"),
    [(0, 0, 1.96), (-1, 5, 1.96), (6, 5, 1.96), (1, 5, 0.0), (1, 5, float("nan")), (True, 5, 1.96)],
)
def test_rejects_invalid_input(k: int, n: int, z: float) -> None:
    with pytest.raises(ValueError, match=r"wilson|z must"):
        wilson(k, n, z)
