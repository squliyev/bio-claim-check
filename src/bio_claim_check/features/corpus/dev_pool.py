"""[RING:features/corpus] The papers a dev answer may use: one question's own dev pool, nothing else.

Why: prompts are tuned on dev questions only, and only on what the sealed dataset says that question's
dev pool is. A live search can return more (test sources, sources from other questions), less (a paper
withdrawn since the build) or different text (an abstract edited since the build). Each of those is
dropped and counted by reason, never silently: an expected source that did not come back is counted
too, so a shrunken pool is visible (I64).
Must not: fetch, read files, top up a short pool, or let a test-split source through for any reason.

No LLM is involved in this module.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from bio_claim_check.features.contracts.corpus import CorpusSplit, QuestionEntry, SourceEntry
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.corpus.serialise import abstract_sha256


class DropReason(StrEnum):
    """Why a source is not passed to the answerer."""

    NOT_IN_POOL = "not_in_pool"
    """Fetched, but not in this question's recorded pool."""
    NOT_DEV = "not_dev"
    """In the question's pool, but in the test split."""
    HASH_DRIFT = "hash_drift"
    """In the dev pool, but its abstract no longer matches the recorded hash."""
    MISSING_EXPECTED = "missing_expected"
    """In the dev pool, but not fetched this time."""
    BEYOND_K = "beyond_k"
    """Usable, but ranked below the top `k`."""


@dataclass(frozen=True, slots=True)
class DevPool:
    """The top-`k` usable papers in recorded rank order, how many were usable, and every drop by reason."""

    papers: tuple[Paper, ...]
    usable: int
    dropped: Mapping[DropReason, int]


def _rank(entry: SourceEntry, question_id: str) -> int | None:
    return next((r.rank for r in entry.ranks if r.question_id == question_id), None)


def dev_pool(
    question: QuestionEntry, entries: Sequence[SourceEntry], fetched: Sequence[Paper], k: int
) -> DevPool:
    """Keep the fetched papers in `question`'s dev pool whose abstract hash matches; rank order, top `k`."""
    if type(k) is not int or k < 1:
        raise ValueError(f"k must be a positive int, got {k!r}")
    by_id = {e.source_id: e for e in entries}
    dropped: Counter[DropReason] = Counter()
    kept: list[tuple[int, Paper]] = []
    for paper in fetched:
        entry = by_id.get(paper.source_id)
        rank = None if entry is None else _rank(entry, question.id)
        if entry is None or rank is None:
            dropped[DropReason.NOT_IN_POOL] += 1
        elif entry.split is not CorpusSplit.DEV:
            dropped[DropReason.NOT_DEV] += 1
        elif abstract_sha256(paper) != entry.abstract_sha256:
            dropped[DropReason.HASH_DRIFT] += 1
        else:
            kept.append((rank, paper))
    fetched_ids = {p.source_id for p in fetched}
    dropped[DropReason.MISSING_EXPECTED] = sum(
        e.split is CorpusSplit.DEV and _rank(e, question.id) is not None and e.source_id not in fetched_ids
        for e in entries
    )
    kept.sort(key=lambda item: item[0])
    dropped[DropReason.BEYOND_K] = max(len(kept) - k, 0)
    return DevPool(
        papers=tuple(p for _, p in kept[:k]),
        usable=len(kept),
        dropped={reason: dropped[reason] for reason in DropReason},
    )
