"""Every trap writer returns the draft for the paper it was asked about, or a counted failure naming it.

Generation cannot tell one writer from another, so each must keep the same promises: a draft is a
`TrapDraft`; a writer that cannot produce one returns a `TrapWriterFailure` for that source and never
raises for a bad output.
"""

from collections.abc import Callable

import pytest

from bio_claim_check.app.container import default_rulepack
from bio_claim_check.features.contracts.labels import FailureKind, OverstatedReason
from bio_claim_check.features.retrieval.in_memory_literature_source import FAKE_CORPUS
from bio_claim_check.features.traps.base_trap_writer import BaseTrapWriter
from bio_claim_check.features.traps.models import TrapDraft, TrapWriterFailure
from bio_claim_check.features.traps.scripted_trap_writer import ScriptedTrapWriter

pytestmark = pytest.mark.contract

PAPER = FAKE_CORPUS[0]
KIND = OverstatedReason.PRECLINICAL_TO_CLINICAL
RULE = next(r for r in default_rulepack().rules if r.reason is KIND)
DRAFT = TrapDraft(parent="OS-912 reduced plaque in mice.", trap="OS-912 reduces plaque in people.")
type Scripted = TrapDraft | FailureKind


def _scripted(out: Scripted) -> BaseTrapWriter:
    return ScriptedTrapWriter({PAPER.source_id: out})


IMPLEMENTATIONS: tuple[type[BaseTrapWriter], ...] = (ScriptedTrapWriter,)
BUILD: dict[type[BaseTrapWriter], Callable[[Scripted], BaseTrapWriter]] = {ScriptedTrapWriter: _scripted}


@pytest.fixture(params=IMPLEMENTATIONS, ids=lambda cls: cls.__name__)
def build(request: pytest.FixtureRequest) -> Callable[[Scripted], BaseTrapWriter]:
    return BUILD[request.param]


def test_every_writer_has_a_builder() -> None:
    assert set(BUILD) == set(IMPLEMENTATIONS)


def test_a_draft_is_returned_as_drafted(build: Callable[[Scripted], BaseTrapWriter]) -> None:
    assert build(DRAFT).draft(KIND, RULE, PAPER) == DRAFT


def test_a_bad_output_is_a_failure_for_that_source(build: Callable[[Scripted], BaseTrapWriter]) -> None:
    out = build(FailureKind.STRUCTURED_OUTPUT).draft(KIND, RULE, PAPER)
    assert out == TrapWriterFailure(source_id=PAPER.source_id, kind=FailureKind.STRUCTURED_OUTPUT)


def test_an_unscripted_source_is_a_failure_not_invented_text() -> None:
    out = ScriptedTrapWriter({}).draft(KIND, RULE, PAPER)
    assert isinstance(out, TrapWriterFailure)
