"""[TEST SUPPORT] Check ports for a "live" claim check that never leaves the process.

A real check fetches by PMID and asks an LLM. Here the paper is fictional paper FAKE:1 under a `MED:` id
and the verifier is scripted, so the live code paths (provenance, `MED:` ids, a named verifier model)
run offline. The scripted output is the overstated preclinical-to-clinical leap of fictional claim o1.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import override

from bio_claim_check.app.container import LiveCheck, default_rulepack_hashed
from bio_claim_check.app.run_record import DeclaredLlm
from bio_claim_check.app.usecases.check_claim import LIVE_CLAIM_ID, CheckPorts
from bio_claim_check.common.model_family import ModelFamily
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.report.models import ModelUse
from bio_claim_check.features.retrieval.citable import RejectReason
from bio_claim_check.features.retrieval.errors import NotCitableError, PaperNotFoundError
from bio_claim_check.features.retrieval.in_memory_literature_source import (
    FAKE_CORPUS,
    InMemoryLiteratureSource,
)
from bio_claim_check.features.verify.scripted_verifier import VERDICT_SCRIPT, ScriptedVerifier
from bio_claim_check.features.verify.verify_llm_agent import VerifyLlmAgent

PMID = "12345678"
SOURCE_ID = f"MED:{PMID}"
CLAIM_TEXT = "OS-912 improves memory in patients with Alzheimer's disease."
PAPER = Paper.model_validate({**FAKE_CORPUS[0].model_dump(), "source_id": SOURCE_ID})
VERIFIER = ModelUse(deployment="verifier-test", family=ModelFamily.ANTHROPIC)
NO_ABSTRACT_PMID = "11111111"
SEALED_PMID = "22222222"
SEALED_ID = f"MED:{SEALED_PMID}"  # stands in for a sealed test-split paper (I84)


class PmidSource(InMemoryLiteratureSource):
    """Europe PMC's `fetch` outcomes by PMID: `PAPER`, one record without an abstract, else not found."""

    @override
    def fetch(self, source_id: SourceId) -> Paper:
        if source_id == SOURCE_ID:
            return PAPER
        if source_id == f"MED:{NO_ABSTRACT_PMID}":
            raise NotCitableError(source_id, RejectReason.NO_ABSTRACT)
        raise PaperNotFoundError(source_id)


def live_check_ports(emitter: EventEmitter | None = None) -> CheckPorts:
    rules = default_rulepack_hashed()
    return CheckPorts(
        literature=PmidSource((PAPER,)),
        verifier=ScriptedVerifier({(LIVE_CLAIM_ID, SOURCE_ID): VERDICT_SCRIPT[("o1", "FAKE:1")]}),
        rules=rules.pack,
        provenance="live",
        rules_sha256=rules.sha256,
        closed_ids=frozenset({SEALED_ID}),
        verifier_model=VERIFIER,
        emitter=emitter,
    )


@contextmanager
def live_check(settings: object, emitter: EventEmitter | None, **_: object) -> Generator[LiveCheck]:
    """A stand-in for `container.build_live_check_ports`."""
    del settings
    declared = DeclaredLlm(
        agent=VerifyLlmAgent.name,
        provider="anthropic",
        deployment=VERIFIER.deployment,
        model_version="test",
        prompt_sha256=VerifyLlmAgent.prompt.sha256,
    )
    yield LiveCheck(ports=live_check_ports(emitter), declared_llm=(declared,))
