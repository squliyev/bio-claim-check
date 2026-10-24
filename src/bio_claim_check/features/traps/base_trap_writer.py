"""[RING:features/traps] The trap writer port: one source in, a (parent, trap) draft or a counted failure out.

Why: generation must not know whether the draft came from a live model or a test script (ADR 0007), and a
writer that cannot produce a draft must say so as a row, not as a crash (the draft file counts failures).
Must not: see other sources, the verifier's output, or any trap already drafted; or decide validity (the
pure gate in `validity` does that, and the author decides the rest).

No LLM is involved in this module.
"""

from abc import ABC, abstractmethod

from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.rulepack import Rule
from bio_claim_check.features.traps.models import TrapDraft, TrapWriterFailure


class BaseTrapWriter(ABC):
    """Drafts a supported claim about one abstract and its rewrite that commits `kind`."""

    @abstractmethod
    def draft(self, kind: OverstatedReason, rule: Rule, paper: Paper) -> TrapDraft | TrapWriterFailure:
        """One draft for `paper`, or a failure naming `paper.source_id`. Never raises for a bad output."""
