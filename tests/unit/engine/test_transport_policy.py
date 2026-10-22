"""Deterministic transport retries and failure classification (I55)."""

import pytest

from bio_claim_check.engine.llm.errors import LlmPromptFilteredError, LlmProviderError, LlmTransportError
from bio_claim_check.engine.llm.transport_policy import (
    MAX_RETRY_AFTER,
    RETRY_DELAYS,
    Outcome,
    TransportFailure,
    classify,
    provider_error_code,
    retry_delay,
    with_retries,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 529])
def test_transient_statuses_are_retried(status: int) -> None:
    assert classify(TransportFailure(status=status)) is Outcome.RETRY


def test_a_connection_failure_is_retried() -> None:
    assert classify(TransportFailure(status=None)) is Outcome.RETRY


def test_a_timeout_is_never_retried() -> None:
    assert classify(TransportFailure(status=None, maybe_billed=True)) is Outcome.GIVE_UP


def test_a_gateway_timeout_is_never_retried() -> None:
    assert classify(TransportFailure(status=504)) is Outcome.GIVE_UP


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 501])
def test_permanent_statuses_are_rejected(status: int) -> None:
    assert classify(TransportFailure(status=status)) is Outcome.REJECT


def test_a_400_content_filter_is_a_prompt_filter() -> None:
    assert classify(TransportFailure(status=400, provider_code="content_filter")) is Outcome.PROMPT_FILTERED
    assert classify(TransportFailure(status=403, provider_code="content_filter")) is Outcome.REJECT


def test_default_delays_follow_the_schedule() -> None:
    assert [retry_delay(i, {}) for i in range(len(RETRY_DELAYS))] == [1.0, 2.0, 4.0]


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"Retry-After": "3"}, 3.0),
        ({"retry-after-ms": "1500", "Retry-After": "9"}, 1.5),
        ({"Retry-After-Ms": "junk", "retry-after": "2.5"}, 2.5),
        ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, 1.0),
        ({"Retry-After": "-4"}, 1.0),
        ({"Retry-After": "nan"}, 1.0),
        ({"Retry-After": "3600"}, MAX_RETRY_AFTER),
    ],
)
def test_provider_hints_are_honoured_validated_and_capped(headers: dict[str, str], expected: float) -> None:
    assert retry_delay(0, headers) == expected


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"error": {"code": "content_filter", "message": "x"}}, "content_filter"),
        ({"type": "error", "error": {"type": "overloaded_error"}}, "overloaded_error"),
        ({"code": "DeploymentNotFound"}, "DeploymentNotFound"),
        ({"error": {"code": " "}}, None),
        ({"error": "text"}, None),
        ("plain text", None),
        (None, None),
    ],
)
def test_provider_error_code_reads_only_the_code(body: object, code: str | None) -> None:
    assert provider_error_code(body) == code


class _Attempts:
    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.calls = 0

    def __call__(self) -> object:
        self.calls += 1
        return self._results.pop(0)


def test_retries_then_succeeds_with_recorded_sleeps_and_hooks() -> None:
    sleeps: list[float] = []
    hooks: list[tuple[int, int | None, float]] = []
    attempt = _Attempts(
        TransportFailure(status=429, headers={"retry-after": "7"}), TransportFailure(None), "ok"
    )

    def hook(transport_attempt: int, status: int | None, delay: float) -> None:
        hooks.append((transport_attempt, status, delay))

    result = with_retries(attempt, deployment="d", sleep=sleeps.append, on_retry=hook)
    assert result == "ok"
    assert sleeps == [7.0, 2.0]
    assert hooks == [(1, 429, 7.0), (2, None, 2.0)]


def test_gives_up_after_the_last_delay() -> None:
    sleeps: list[float] = []
    attempt = _Attempts(*[TransportFailure(status=503)] * 4)
    with pytest.raises(LlmTransportError) as caught:
        with_retries(attempt, deployment="d", sleep=sleeps.append)
    assert (caught.value.status, caught.value.attempts) == (503, 4)
    assert sleeps == list(RETRY_DELAYS)
    assert attempt.calls == 4


def test_a_timeout_fails_at_once_and_says_why() -> None:
    attempt = _Attempts(TransportFailure(status=None, maybe_billed=True))
    with pytest.raises(LlmTransportError, match="may have been billed") as caught:
        with_retries(attempt, deployment="d", sleep=lambda _s: None)
    assert caught.value.attempts == 1


def test_a_gateway_timeout_fails_at_once_and_says_why() -> None:
    attempt = _Attempts(TransportFailure(status=504))
    with pytest.raises(LlmTransportError, match="may have been billed") as caught:
        with_retries(attempt, deployment="d", sleep=lambda _s: None)
    assert (caught.value.status, caught.value.attempts) == (504, 1)


def test_a_rejection_is_not_retried_and_carries_only_the_code() -> None:
    attempt = _Attempts(TransportFailure(status=401, provider_code="Unauthorized"))
    with pytest.raises(LlmProviderError) as caught:
        with_retries(attempt, deployment="d", sleep=lambda _s: None)
    assert (caught.value.status, caught.value.provider_code) == (401, "Unauthorized")
    assert attempt.calls == 1


def test_a_prompt_filter_raises_its_own_error() -> None:
    attempt = _Attempts(TransportFailure(status=400, provider_code="content_filter"))
    with pytest.raises(LlmPromptFilteredError):
        with_retries(attempt, deployment="d", sleep=lambda _s: None)
