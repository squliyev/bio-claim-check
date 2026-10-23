"""`LlmVerifier`: output-level failures are counted per pair; every other error stops the run (I70)."""

import pytest
from tests.support.llm import response, spec

from bio_claim_check.app.container import default_rulepack
from bio_claim_check.common.errors import BccError
from bio_claim_check.engine.llm.errors import (
    LlmBudgetExceededError,
    LlmPromptFilteredError,
    LlmProviderError,
    LlmRequestError,
    LlmTransportError,
    LlmUnexpectedResponseError,
)
from bio_claim_check.engine.llm.messages import FinishReason, LlmResponse
from bio_claim_check.engine.llm.scripted_llm_client import ScriptedLlmClient
from bio_claim_check.features.contracts.labels import FailureKind
from bio_claim_check.features.contracts.verdict import Claim, VerifierFailure
from bio_claim_check.features.retrieval.in_memory_literature_source import FAKE_CORPUS
from bio_claim_check.features.verify.llm_verifier import LlmVerifier
from bio_claim_check.features.verify.verify_llm_agent import VerifyLlmAgent

pytestmark = pytest.mark.unit

PAPER = FAKE_CORPUS[0]
CLAIM = Claim(id="c1", text="OS-912 reduced plaque in mice.", cites=(PAPER.source_id,))


def _verify(*scripted: LlmResponse | BccError) -> VerifierFailure | object:
    verifier = LlmVerifier(VerifyLlmAgent(ScriptedLlmClient(scripted), spec()))
    return verifier.verify(CLAIM, PAPER, default_rulepack())


@pytest.mark.parametrize(
    ("scripted", "kind"),
    [
        ((response("{", finish=FinishReason.LENGTH),), FailureKind.STRUCTURED_OUTPUT),
        ((response("no"), response("still no")), FailureKind.STRUCTURED_OUTPUT),
        ((response("{}", finish=FinishReason.CONTENT_FILTER),), FailureKind.CONTENT_FILTERED),
        ((LlmPromptFilteredError(deployment="model-a"),), FailureKind.CONTENT_FILTERED),
    ],
    ids=["truncated", "invalid_twice", "response_filtered", "prompt_filtered"],
)
def test_an_output_level_failure_is_counted_for_the_pair(
    scripted: tuple[LlmResponse | BccError, ...], kind: FailureKind
) -> None:
    assert _verify(*scripted) == VerifierFailure(claim_id=CLAIM.id, source_id=PAPER.source_id, kind=kind)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 408, 422, 429, 500, 503])
def test_every_provider_rejection_stops_the_run(status: int) -> None:
    with pytest.raises(LlmProviderError):
        _verify(LlmProviderError(deployment="model-a", status=status, provider_code=None))


@pytest.mark.parametrize(
    "error",
    [
        LlmTransportError(deployment="model-a", status=None, attempts=3, reason="timeout"),
        LlmUnexpectedResponseError("an unknown shape"),
        LlmBudgetExceededError("spent"),
        LlmRequestError("a seed"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_an_infrastructure_error_stops_the_run(error: BccError) -> None:
    with pytest.raises(type(error)):
        _verify(error)
