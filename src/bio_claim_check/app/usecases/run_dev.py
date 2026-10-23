"""[RING:app/usecases] Run the full product flow on one dev question, from its sealed dev pool only.

Why: the verifier is tuned on dev questions (S12b), so the dev path must be the very flow a live `run`
uses: the dev preflight and pool of `answer dev` (`dev_papers`), then `check_answer` from `run`. It adds
nothing of its own except the canonical record, which keeps the pool's drops by reason (ADR 0011) beside
the report, as `DevAnswerRecord` does for `answer dev`.
Must not: do I/O itself, touch a test question or a test-split source, top up a short pool, or diverge
from `check_answer`.
"""

from collections.abc import Mapping
from typing import Annotated

from pydantic import Field

from bio_claim_check.app.usecases.answer_dev import dev_papers
from bio_claim_check.app.usecases.run import RunPorts, check_answer
from bio_claim_check.common.models import NonBlankStr, ValidatedModel
from bio_claim_check.features.contracts.corpus import CorpusSpec
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.corpus.dev_pool import DropReason
from bio_claim_check.features.report.models import Report


class DevRunRecord(ValidatedModel):
    """The canonical `report.json` of `run --dev`: the question id, the pool's counts and the report."""

    question_id: NonBlankStr
    k: Annotated[int, Field(strict=True, ge=1)]
    papers: tuple[SourceId, ...]
    usable: Annotated[int, Field(strict=True, ge=0)]
    dropped: dict[DropReason, Annotated[int, Field(strict=True, ge=0)]]
    report: Report


def run_dev(
    c: RunPorts,
    files: Mapping[str, bytes],
    spec: CorpusSpec,
    question_id: str,
    mode: AnswerMode,
    *,
    k: int,
) -> DevRunRecord:
    """Seal check and dev pool (bad input raises before any fetch), then answer, check and verify."""
    question, pool = dev_papers(c.literature, files, spec, question_id, k=k, emitter=c.emitter)
    report = check_answer(c, question.text, pool.papers, mode)
    return DevRunRecord(
        question_id=question.id,
        k=k,
        papers=tuple(p.source_id for p in pool.papers),
        usable=pool.usable,
        dropped={reason: pool.dropped.get(reason, 0) for reason in DropReason},
        report=report,
    )
