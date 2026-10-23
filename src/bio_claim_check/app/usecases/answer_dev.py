"""[RING:app/usecases] Answer one dev question live, from that question's sealed dev pool only.

Why: prompts are tuned on dev questions, and the tuning is only honest if the answerer sees exactly the
dev pool the sealed dataset records. This flow checks the dataset first (seal, hashes, splits) and
refuses before any fetch if it is not intact, refuses any question that is not in the dev split, re-runs
the question's recorded search (the same request as the build, so a warm cache answers it), and passes
only the papers `dev_pool` keeps. Every drop is counted by reason (I64). The deterministic checks run on
the answer exactly as in `run_question`.
Must not: do I/O itself (it receives the dataset bytes and its ports), verify claims (S12), touch a test
question or a test-split source, or top up a short pool.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from bio_claim_check.common.errors import BccError
from bio_claim_check.engine.events.llm_events import LlmCallFailed, LlmCallFinished
from bio_claim_check.engine.events.pipeline_event import PipelineEvent
from bio_claim_check.features.answer.base_answerer import BaseAnswerer
from bio_claim_check.features.checks.citations import invented_citations
from bio_claim_check.features.checks.self_containment import dangling_claims
from bio_claim_check.features.contracts.answer import Answer
from bio_claim_check.features.contracts.corpus import CorpusSpec, CorpusSplit, QuestionEntry, SourceEntry
from bio_claim_check.features.contracts.finding import Finding
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.corpus.dev_pool import DevPool, dev_pool
from bio_claim_check.features.corpus.layout import DEV_SOURCES, QUESTIONS, TEST_SOURCES
from bio_claim_check.features.corpus.seal import dataset_problems
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource


class DevAnswerInputError(BccError):
    """The dataset is not intact and sealed, or the question is not a dev question. One line per problem."""

    code = "answer.dev_input"

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
    if type(k) is not int or k < 1:
        raise ValueError(f"k must be a positive int, got {k!r}")
    if problems := dataset_problems(files, spec):
        raise DevAnswerInputError(["the dataset is not intact and sealed:", *problems])
    questions = {q.id: q for q in _rows(files[QUESTIONS], QuestionEntry)}
    question = questions.get(question_id)
    if question is None:
        raise DevAnswerInputError([f"no question {question_id!r} in the dataset"])
    if question.split is not CorpusSplit.DEV:
        raise DevAnswerInputError(
            [f"{question_id} is a {question.split.value} question; only dev questions may be used"]
        )
    entries = [*_rows(files[DEV_SOURCES], SourceEntry), *_rows(files[TEST_SOURCES], SourceEntry)]

    fetched = ports.source.search(question.query, limit=spec.pool_hits)
    pool = dev_pool(question, entries, fetched, k)
    if not pool.papers:
        raise EmptyDevPoolError(f"{question_id}: no paper of its dev pool came back usable")

    answer = ports.answerer.answer(question.text, pool.papers, mode)
    if (answer.question, answer.mode) != (question.text, mode):
        raise ValueError("the answer does not echo the question and mode it was asked")
    retrieved = {p.source_id for p in pool.papers}
    findings = (*invented_citations(answer, retrieved), *dangling_claims(answer))
    return DevAnswer(question=question, pool=pool, answer=answer, findings=findings)


@dataclass(frozen=True, slots=True)
class CallTally:
    """LLM calls split into live, cache hits and failed; tokens are summed over finished live calls only.

    A replayed call costs nothing now, so counting its tokens would make a replay look like new spend.
    A failed call may still have been billed, but its usage is unknown, so it is counted, never summed.
    A provider that does not report reasoning tokens is counted in `reasoning_unreported`, never as 0.
    No deployment has a price yet (`ModelSpec.price is None`), so the CLI shows money as "unpriced".
    """

    live_calls: int = 0
    cached_calls: int = 0
    failed_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    reasoning_unreported: int = 0


def tally_calls(events: Iterable[PipelineEvent]) -> CallTally:
    live = cached = failed = tokens_in = tokens_out = reasoning = unreported = 0
    for event in events:
        if isinstance(event, LlmCallFailed):
            failed += 1
            continue
        if not isinstance(event, LlmCallFinished):
            continue
        if event.cache_hit:
            cached += 1
            continue
        live += 1
        tokens_in += event.input_tokens
        tokens_out += event.output_tokens
        if event.reasoning_tokens is None:
            unreported += 1
        else:
            reasoning += event.reasoning_tokens
    return CallTally(live, cached, failed, tokens_in, tokens_out, reasoning, unreported)
