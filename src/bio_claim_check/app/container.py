"""[RING:app] Composition root: the one place concrete implementations are chosen and wired.

Why: features depend on ports, never on adapters; something has to pick the adapters, and only `app`
may (ADR 0002). Today only the fake wiring exists (S05); live wiring arrives with real adapters (S12).
Must not: hold logic. It builds objects and hands them to a use case.
"""

from dataclasses import dataclass

from bio_claim_check.features.answer.fakes import ScriptedAnswerer
from bio_claim_check.features.answer.ports import Answerer
from bio_claim_check.features.contracts.rulepack import RulePack
from bio_claim_check.features.report.models import Provenance
from bio_claim_check.features.retrieval.fakes import FakeLiteratureSource
from bio_claim_check.features.retrieval.ports import LiteratureSource
from bio_claim_check.features.verify.fakes import ScriptedVerifier
from bio_claim_check.features.verify.ports import Verifier
from bio_claim_check.infrastructure.rulepack_yaml import load_default_rulepack


@dataclass(frozen=True, slots=True)
class Container:
    """Everything a run needs, chosen once."""

    literature: LiteratureSource
    answerer: Answerer
    verifier: Verifier
    rules: RulePack
    provenance: Provenance


def build_fake_container() -> Container:
    """Fictional papers, scripted answers and verdicts. Needs no settings, network or `.env`."""
    return Container(
        literature=FakeLiteratureSource(),
        answerer=ScriptedAnswerer(),
        verifier=ScriptedVerifier(),
        rules=load_default_rulepack(),
        provenance="fake",
    )
