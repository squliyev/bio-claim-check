"""[RING:app/usecases] Answer one dev question live, from that question's sealed dev pool only.

Why: prompts are tuned on dev questions, and the tuning is only honest if the answerer sees exactly the
dev pool the sealed dataset records. This flow checks the dataset first (seal, hashes, splits) and
refuses before any fetch if it is not intact, refuses any question that is not in the dev split, re-runs
the question's recorded search (the same request as the build, so a warm cache answers it), and passes
only the papers `dev_pool` keeps. Every drop is counted by reason (I64). The deterministic checks run on
the answer exactly as in `run_question`.
Stage events (`retrieve`, `answer`) go to the ports' emitter when one is given; the usage fold moved
to `engine.events.call_tally` in S11, and `DevAnswerRecord` is what the run record publishes.
Must not: do I/O itself (it receives the dataset bytes and its ports), verify claims (S12), touch a test
question or a test-split source, or top up a short pool.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated

from pydantic import Field

from bio_claim_check.common.errors import BccError
from bio_claim_check.common.models import NonBlankStr, ValidatedModel
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.stage_events import stage
from bio_claim_check.features.answer.base_answerer import BaseAnswerer
from bio_claim_check.features.checks.citations import invented_citations
from bio_claim_check.features.checks.self_containment import dangling_claims
from bio_claim_check.features.contracts.answer import Answer
from bio_claim_check.features.contracts.corpus import CorpusSpec, CorpusSplit, QuestionEntry, SourceEntry
from bio_claim_check.features.contracts.finding import Finding
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.contracts.verdict import Claim
from bio_claim_check.features.corpus.dev_pool import DevPool, DropReason, dev_pool
from bio_claim_check.features.corpus.layout import DEV_SOURCES, QUESTIONS, TEST_SOURCES
from bio_claim_check.features.corpus.seal import dataset_problems
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource


class DevAnswerInputError(BccError):
    """The question is not in the dataset, or is not a dev question. One line per problem."""

    code = "answer.dev_input"

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = tuple(problems)


class DevDatasetError(BccError):
    """The dataset is not intact and sealed. One line per problem."""

    code = "answer.dataset"

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = tuple(problems)


class EmptyDevPoolError(BccError):
    """No paper of the question's dev pool survived the fetch; there is nothing honest to answer from."""

    code = "answer.empty_pool"


@dataclass(frozen=True, slots=True)
class DevAnswerPorts:
    source: BaseLiteratureSource
    answerer: BaseAnswerer
    emitter: EventEmitter | None = None  # receives the `retrieve` and `answer` stage events (S11)


@dataclass(frozen=True, slots=True)
class DevAnswer:
    question: QuestionEntry
    pool: DevPool
    answer: Answer
    findings: tuple[Finding, ...]


def _rows[M: SourceEntry | QuestionEntry](data: bytes, model: type[M]) -> list[M]:
    return [model.model_validate_json(line) for line in data.decode("utf-8").splitlines()]


def answer_dev(
    ports: DevAnswerPorts,
    files: Mapping[str, bytes],
    spec: CorpusSpec,
    question_id: str,
    mode: AnswerMode,
    *,
    k: int,
) -> DevAnswer:
    """Seal check, dev-only pool, answer, then the deterministic checks. Bad input raises before any fetch."""
    question, pool = dev_papers(ports.source, files, spec, question_id, k=k, emitter=ports.emitter)

    with stage(ports.emitter, "answer"):
        answer = ports.answerer.answer(question.text, pool.papers, mode)
    if (answer.question, answer.mode) != (question.text, mode):
        raise ValueError("the answer does not echo the question and mode it was asked")
    retrieved = {p.source_id for p in pool.papers}
    findings = (*invented_citations(answer, retrieved), *dangling_claims(answer))
    return DevAnswer(question=question, pool=pool, answer=answer, findings=findings)


def dev_papers(
    source: BaseLiteratureSource,
    files: Mapping[str, bytes],
    spec: CorpusSpec,
    question_id: str,
    *,
    k: int,
    emitter: EventEmitter | None,
) -> tuple[QuestionEntry, DevPool]:
    """The dev preflight and pool shared by `answer dev` and `run --dev`: seal check, dev question only,
    the recorded search, dev-split papers only. Bad input raises before any fetch; an empty pool raises."""
    if type(k) is not int or k < 1:
        raise ValueError(f"k must be a positive int, got {k!r}")
    if problems := dataset_problems(files, spec):
        raise DevDatasetError(problems)
    questions = {q.id: q for q in _rows(files[QUESTIONS], QuestionEntry)}
    question = questions.get(question_id)
    if question is None:
        raise DevAnswerInputError([f"no question {question_id!r} in the dataset"])
    if question.split is not CorpusSplit.DEV:
        raise DevAnswerInputError(
            [f"{question_id} is a {question.split.value} question; only dev questions may be used"]
        )
    entries = [*_rows(files[DEV_SOURCES], SourceEntry), *_rows(files[TEST_SOURCES], SourceEntry)]

    with stage(emitter, "retrieve"):
        fetched = source.search(question.query, limit=spec.pool_hits)
    pool = dev_pool(question, entries, fetched, k)
    if not pool.papers:
        raise EmptyDevPoolError(f"{question_id}: no paper of its dev pool came back usable")
    return question, pool


class DevAnswerRecord(ValidatedModel):
    """The canonical `answer.json` of an `answer dev` run (ADR 0018): ids, counts, claims and findings.

    No abstract text: it is in the cache and the dataset. The claims are the model's output.
    """

    question_id: NonBlankStr
    mode: AnswerMode
    k: Annotated[int, Field(strict=True, ge=1)]
    papers: tuple[SourceId, ...]
    usable: Annotated[int, Field(strict=True, ge=0)]
    dropped: dict[DropReason, Annotated[int, Field(strict=True, ge=0)]]
    claims: tuple[Claim, ...]
    findings: tuple[Finding, ...]


def dev_answer_record(result: DevAnswer, k: int) -> DevAnswerRecord:
    return DevAnswerRecord(
        question_id=result.question.id,
        mode=result.answer.mode,
        k=k,
        papers=tuple(p.source_id for p in result.pool.papers),
        usable=result.pool.usable,
        dropped={reason: result.pool.dropped.get(reason, 0) for reason in DropReason},
        claims=result.answer.claims,
        findings=result.findings,
    )
