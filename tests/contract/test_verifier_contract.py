"""Every verifier judges one pair, finalises in code, and returns a counted failure for a bad output (I70).

`run_question` cannot tell one verifier from another, so each must keep the same promises: the verdict
names the pair it was asked about, the evidence status comes from `Verdict.finalise` against the cleaned
abstract (a fabricated quote is caught), and a pair-level output problem is a `VerifierFailure`.
"""

from collections.abc import Callable

import pytest

from bio_claim_check.app.container import default_rulepack
from bio_claim_check.engine.llm.messages import FinishReason
from bio_claim_check.engine.llm.scripted_llm_client import ScriptedLlmClient
from bio_claim_check.features.contracts.labels import EvidenceStatus, FailureKind, Label
from bio_claim_check.features.contracts.verdict import Claim, Verdict, VerifierFailure, VerifierOutput
from bio_claim_check.features.retrieval.in_memory_literature_source import FAKE_CORPUS
from bio_claim_check.features.verify.base_verifier import BaseVerifier
from bio_claim_check.features.verify.llm_verifier import LlmVerifier
from bio_claim_check.features.verify.scripted_verifier import ScriptedVerifier
from bio_claim_check.features.verify.verify_llm_agent import VerifyLlmAgent
from tests.support.llm import response, spec

pytestmark = pytest.mark.contract

PAPER = FAKE_CORPUS[0]
CLAIM = Claim(id="c1", text="OS-912 reduced plaque in mice.", cites=(PAPER.source_id,))
type Scripted = VerifierOutput | FailureKind


def _scripted(out: Scripted) -> BaseVerifier:
    return ScriptedVerifier({(CLAIM.id, PAPER.source_id): out})


def _llm(out: Scripted) -> BaseVerifier:
    reply = (
        response(out.model_dump_json())
        if isinstance(out, VerifierOutput)
        else response("{", finish=FinishReason.LENGTH)
    )
    return LlmVerifier(VerifyLlmAgent(ScriptedLlmClient([reply]), spec()))


IMPLEMENTATIONS: tuple[type[BaseVerifier], ...] = (ScriptedVerifier, LlmVerifier)
BUILD: dict[type[BaseVerifier], Callable[[Scripted], BaseVerifier]] = {
    ScriptedVerifier: _scripted,
    LlmVerifier: _llm,
}


@pytest.fixture(params=IMPLEMENTATIONS, ids=lambda cls: cls.__name__)
def build(request: pytest.FixtureRequest) -> Callable[[Scripted], BaseVerifier]:
    return BUILD[request.param]


def _out(evidence: str | None) -> VerifierOutput:
    return VerifierOutput(label=Label.SUPPORTED, overstated_reason=None, evidence=evidence, reason="Stated.")


def test_every_verifier_has_a_builder() -> None:
    assert set(BUILD) == set(IMPLEMENTATIONS)


def test_a_verdict_names_its_pair_and_locates_a_real_quote(build: Callable[[Scripted], BaseVerifier]) -> None:
    verdict = build(_out("OS-912 (10 mg/kg) reduced amyloid plaque load by 38%")).verify(
        CLAIM, PAPER, default_rulepack()
    )
    assert isinstance(verdict, Verdict)
    assert (verdict.claim_id, verdict.source_id) == (CLAIM.id, PAPER.source_id)
    assert verdict.evidence_status is EvidenceStatus.LOCATED


def test_a_fabricated_quote_is_caught_by_code(build: Callable[[Scripted], BaseVerifier]) -> None:
    verdict = build(_out("OS-912 cured dementia in every patient")).verify(CLAIM, PAPER, default_rulepack())
    assert isinstance(verdict, Verdict)
    assert verdict.evidence_status is EvidenceStatus.ABSENT


def test_a_bad_output_is_a_counted_failure_for_the_pair(build: Callable[[Scripted], BaseVerifier]) -> None:
    failure = build(FailureKind.STRUCTURED_OUTPUT).verify(CLAIM, PAPER, default_rulepack())
    assert failure == VerifierFailure(
        claim_id=CLAIM.id, source_id=PAPER.source_id, kind=FailureKind.STRUCTURED_OUTPUT
    )
