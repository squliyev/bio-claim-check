"""[RING:features/bench] Statistics for the benchmark: bootstrap, paired intervals, McNemar (S16).

Why a separate module: these functions must be reproducible to the last digit, so they are pure,
deterministic and tested against reference values.

No LLM is involved in this module; import-linter contract ``no-llm-in-deterministic-code`` enforces it
(ADR 0003).
"""

import math
from typing import Final

Z_95: Final = 1.959964  # two-sided 95 % normal quantile, to the precision used in Newcombe (1998)


def wilson(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a proportion k/n (Wilson 1927; Newcombe 1998, method 3).

    Used for the sieve-precision audit (fixed n, so the interval is valid). Raises ValueError unless
    n ≥ 1 and 0 ≤ k ≤ n; the bounds are clamped to [0, 1] against rounding.
    """
    if type(k) is not int or type(n) is not int or n < 1 or not 0 <= k <= n:
        raise ValueError(f"wilson needs integers n >= 1 and 0 <= k <= n, got k={k!r}, n={n!r}")
    if type(z) is bool or not (math.isfinite(z) and z > 0):
        raise ValueError(f"z must be a finite positive number, got {z!r}")
    p = k / n
    z2 = z * z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)
