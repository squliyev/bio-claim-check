"""[RING:engine/llm] Token usage, prices and the spend of a run: one tested piece of arithmetic.

Why: a cost table that double-counts reasoning tokens, or shows 0 for a model nobody priced, is a number
the code did not produce. Usage is what the provider reported (measured, never estimated); a price is
supplied by a person with its date and source; a cost exists only when every live call was priced.
Must not: estimate tokens, invent a price, or round (Decimal end to end; JSON carries decimal strings).

Pure values: makes no provider call. (It is LLM vocabulary, so it does not carry the
ADR 0003 deterministic marker.)
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BeforeValidator, Field, model_validator

from bio_claim_check.common.models import NonBlankStr, ValidatedModel

NonNegInt = Annotated[int, Field(strict=True, ge=0)]


def _no_binary_float(value: object) -> object:
    if isinstance(value, bool | float):
        raise ValueError("give money as a decimal string or an integer, never a float or bool")
    return value


Money = Annotated[Decimal, BeforeValidator(_no_binary_float), Field(ge=0, allow_inf_nan=False)]
"""A finite, non-negative Decimal; JSON input as a string (floats would round silently)."""

_PER_MTOK = -6  # prices are per million tokens: scale by 10^-6, exactly


class Usage(ValidatedModel):
    """Provider-reported tokens for one call (or a sum of calls).

    `reasoning_tokens` are part of `output_tokens` and `cached_input_tokens` part of `input_tokens`
    (the engine's normalised contract; each provider codec maps its raw fields onto it, S09).
    `reasoning_tokens` is None when the provider did not report it: "not reported" is never written as
    0, and is never estimated (I51). A sum that includes a non-reporting call is None as well, because
    the true total is unknown. `Usage.zero()` (reasoning 0) is the identity for sums: no calls, no tokens.
    """

    input_tokens: NonNegInt = 0
    output_tokens: NonNegInt = 0
    reasoning_tokens: NonNegInt | None = None
    cached_input_tokens: NonNegInt = 0

    @model_validator(mode="after")
    def _subsets(self) -> Self:
        if self.reasoning_tokens is not None and self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning_tokens are part of output_tokens, so cannot exceed them")
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached_input_tokens are part of input_tokens, so cannot exceed them")
        return self

    @classmethod
    def zero(cls) -> Self:
        """The empty sum: no calls, so every count (reasoning included) is a measured 0."""
        return cls(reasoning_tokens=0)

    def __add__(self, other: Self) -> Self:
        reasoning = (
            None
            if self.reasoning_tokens is None or other.reasoning_tokens is None
            else self.reasoning_tokens + other.reasoning_tokens
        )
        return type(self)(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=reasoning,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
        )


class Price(ValidatedModel):
    """Prices per million tokens, as a person read them from a pricing page on a given day."""

    input_per_mtok: Money
    output_per_mtok: Money
    cached_input_per_mtok: Money | None = None
    as_of: date
    source: NonBlankStr


def cost(usage: Usage, price: Price | None) -> Decimal | None:
    """The cost of `usage`, or None when unpriced (never 0).

    Cached input is charged at its own price, or at the input price when none is given (an upper bound).
    Reasoning tokens are already inside output tokens, so they are not charged twice.
    """
    if price is None:
        return None
    cached_rate = price.input_per_mtok if price.cached_input_per_mtok is None else price.cached_input_per_mtok
    total = (
        (usage.input_tokens - usage.cached_input_tokens) * price.input_per_mtok
        + usage.cached_input_tokens * cached_rate
        + usage.output_tokens * price.output_per_mtok
    )
    return total.scaleb(_PER_MTOK)


class Spend(ValidatedModel):
    """What a run paid for: live calls only. Replayed (cache-hit) calls are counted, but cost nothing.

    `cost` becomes None as soon as one live call is unpriced and stays None: a partial sum would read
    as the full cost. An *unmeasured* call reached the provider but returned no usage (e.g. a prompt
    rejected by a content filter with HTTP 400): it is counted in `unmeasured_calls`, adds nothing to
    `usage` (never an invented 0), and makes `cost` None, because what it was billed is unknown.
    """

    calls: NonNegInt = 0
    usage: Usage = Field(default_factory=Usage.zero)
    cost: Money | None = Decimal(0)
    cache_hits: NonNegInt = 0
    replayed_usage: Usage = Field(default_factory=Usage.zero)
    unmeasured_calls: NonNegInt = 0

    def record(self, *, paid: Usage | None, usage: Usage, price: Price | None) -> Self:
        """Add one call: `paid` is what this run was billed for, None for a cache hit.

        `usage` is what producing the answer consumed; on a cache hit it is counted as replayed.
        """
        if paid is None:
            return type(self)(
                calls=self.calls,
                usage=self.usage,
                cost=self.cost,
                cache_hits=self.cache_hits + 1,
                replayed_usage=self.replayed_usage + usage,
                unmeasured_calls=self.unmeasured_calls,
            )
        added = cost(paid, price)
        return type(self)(
            calls=self.calls + 1,
            usage=self.usage + paid,
            cost=None if self.cost is None or added is None else self.cost + added,
            cache_hits=self.cache_hits,
            replayed_usage=self.replayed_usage,
            unmeasured_calls=self.unmeasured_calls,
        )

    def record_unmeasured(self) -> Self:
        """Add one live call whose usage the provider did not report; its cost is unknown."""
        return type(self)(
            calls=self.calls,
            usage=self.usage,
            cost=None,
            cache_hits=self.cache_hits,
            replayed_usage=self.replayed_usage,
            unmeasured_calls=self.unmeasured_calls + 1,
        )
