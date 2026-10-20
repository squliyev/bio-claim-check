"""[RING:features/verify] A scripted verifier for demos and tests.

Why: the walking skeleton (S05) needs verdicts without an LLM. The script supplies only what an LLM
would (a `VerifierOutput`); the evidence status still comes from code, through `Verdict.finalise`
against the real cleaned abstract, so a scripted quote that is not in the abstract is caught exactly
as a real one would be.
Must not: build a `Verdict` any other way, or be wired into a live run.

No LLM is involved in this module.
"""

from collections.abc import Mapping
from typing import override

from bio_claim_check.features.contracts.ids import ClaimId, SourceId
from bio_claim_check.features.contracts.labels import FailureKind, Label, OverstatedReason
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.rulepack import RulePack
from bio_claim_check.features.contracts.verdict import Claim, Verdict, VerifierFailure, VerifierOutput
from bio_claim_check.features.verify.base_verifier import BaseVerifier

type Script = Mapping[tuple[ClaimId, SourceId], VerifierOutput | FailureKind]


def _out(
    label: Label, evidence: str | None, reason: str, why: OverstatedReason | None = None
) -> VerifierOutput:
    return VerifierOutput(label=label, overstated_reason=why, evidence=evidence, reason=reason)


VERDICT_SCRIPT: Script = {
    ("s1", "FAKE:1"): _out(
        Label.SUPPORTED, "OS-912 (10 mg/kg) reduced amyloid plaque load by 38%", "The mouse result is stated."
    ),
    ("s2", "FAKE:3"): _out(
        Label.SUPPORTED,
        "OS-912 use was associated with a lower incidence of dementia",
        "The association is stated as an association.",
    ),
    ("s2", "FAKE:4"): _out(
        Label.NOT_IN_SOURCE, None, "The review does not mention OS-912 or dementia incidence."
    ),
    ("s3", "FAKE:2"): _out(
        Label.SUPPORTED,
        "HX-15 did not significantly change cognitive scores (p = 0.41)",
        "The null result is stated.",
    ),
    ("o1", "FAKE:1"): _out(
        Label.OVERSTATED,
        "In APP/PS1 mice, OS-912 (10 mg/kg) reduced amyloid plaque load",
        "A plaque result in mice is stated as a cognitive benefit in patients.",
        OverstatedReason.PRECLINICAL_TO_CLINICAL,
    ),
    ("o2", "FAKE:3"): _out(
        Label.OVERSTATED,
        "OS-912 use was associated with a lower incidence of dementia",
        "An observational association is stated as prevention.",
        OverstatedReason.CORRELATION_AS_CAUSATION,
    ),
    ("o3", "FAKE:2"): _out(
        Label.SUPPORTED,
        "HX-15 significantly improved cognitive scores",
        "A fabricated quote: the abstract reports no significant change.",
    ),
    ("o4", "FAKE:1"): _out(
        Label.SUPPORTED,
        "OS-912 (10 mg/kg) reduced amyloid plaque load by 36%",
        "A misquoted number: the abstract says 38%.",
    ),
    ("o6", "FAKE:4"): FailureKind.STRUCTURED_OUTPUT,
}
"""Scripted model output per (claim, source). `FAKE:99` (claim o5) is never retrieved, so never here."""


class ScriptedVerifier(BaseVerifier):
    """Looks up the scripted output for a pair and finalises it against the paper's cleaned abstract."""

    def __init__(self, script: Script = VERDICT_SCRIPT) -> None:
        self._script = script

    @override
    def verify(self, claim: Claim, paper: Paper, rules: RulePack) -> Verdict | VerifierFailure:
        del rules  # scripted: the rule pack only shapes a real verifier's prompt
        scripted = self._script.get((claim.id, paper.source_id))
        if scripted is None:
            raise KeyError(f"no scripted verdict for {claim.id}/{paper.source_id}")
        if isinstance(scripted, FailureKind):
            return VerifierFailure(claim_id=claim.id, source_id=paper.source_id, kind=scripted)
        return Verdict.finalise(claim.id, paper.source_id, scripted, paper.abstract)
