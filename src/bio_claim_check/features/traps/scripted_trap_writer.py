"""[RING:features/traps] A scripted trap writer for tests and offline runs.

Why: generation, the gate and the audit sheet must be testable without a model. The script maps a source
to the draft (or failure) a model would have returned; an unscripted source is a structured-output
failure, exactly as a model that returned nothing usable would be.
Must not: be wired into a live run, or invent text for an unscripted source.

No LLM is involved in this module.
"""

from collections.abc import Mapping
from typing import override

from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.labels import FailureKind, OverstatedReason
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.rulepack import Rule
from bio_claim_check.features.traps.base_trap_writer import BaseTrapWriter
from bio_claim_check.features.traps.models import TrapDraft, TrapWriterFailure

type TrapScript = Mapping[SourceId, TrapDraft | FailureKind]


class ScriptedTrapWriter(BaseTrapWriter):
    def __init__(self, script: TrapScript) -> None:
        self._script = dict(script)

    @override
    def draft(self, kind: OverstatedReason, rule: Rule, paper: Paper) -> TrapDraft | TrapWriterFailure:
        out = self._script.get(paper.source_id, FailureKind.STRUCTURED_OUTPUT)
        if isinstance(out, FailureKind):
            return TrapWriterFailure(source_id=paper.source_id, kind=out)
        return out
