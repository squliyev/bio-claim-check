"""[RING:features/traps] Which dev sources get a trap of which kind, in a public, reproducible order.

Why: the trap set must not be hand-picked, and a larger `--per-kind` must extend an earlier run rather
than reshuffle it (so earlier drafts stay cache hits). Each eligible source is therefore assigned once, to
its scarcest candidate kind (fewest eligible sources, then the order of `kinds`), before anything is cut.
Within a kind the order is `sha256(TRAP_SALT|source_id)`, and at most one source per cluster is used, so
near-duplicate papers do not inflate a kind. A kind with fewer sources than `per_kind` gets every source
it has (the shortfall is the caller's to report); only a kind with none is refused. The one-pass greedy
assignment can leave a kind short that a full matching would fill; it is kept because a matching would
reorder picks as `per_kind` grows, breaking the cache-hit top-up. A sieve candidate is not a label: the
author's audit is the eligibility check. Only dev sources are eligible (I78); a source that can never be a
trap (retracted, a review, unindexed) has no candidates by the `SourceEntry` contract, so it is never
picked.
Must not: read files, call a model, or look at the test split.

No LLM is involved in this module.
"""

import hashlib
from collections.abc import Collection, Sequence

from bio_claim_check.common.errors import BccError
from bio_claim_check.common.models import NonBlankStr, Sha256Hex, ValidatedModel
from bio_claim_check.features.contracts.corpus import CorpusSplit, SourceEntry
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.traps.models import TRAP_SALT


class Pick(ValidatedModel):
    """One sampled source: the kind to draft and the question whose pool holds the source."""

    kind: OverstatedReason
    source_id: SourceId
    question_id: NonBlankStr
    abstract_sha256: Sha256Hex


class TrapSamplingError(BccError):
    """Some kind has no eligible dev source at all; nothing was drafted."""

    code = "traps.infeasible"

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = tuple(problems)


def _order(source_id: SourceId) -> tuple[str, str]:
    return hashlib.sha256(f"{TRAP_SALT}|{source_id}".encode()).hexdigest(), source_id


def _question(entry: SourceEntry, questions: Collection[str], max_rank: int) -> str | None:
    """The dev question where the source ranks best (rank, then question id), within the retrieved pool."""
    ranks = sorted((r.rank, r.question_id) for r in entry.ranks if r.question_id in questions)
    return ranks[0][1] if ranks and ranks[0][0] <= max_rank else None


def sample(
    entries: Sequence[SourceEntry],
    kinds: Sequence[OverstatedReason],
    per_kind: int,
    *,
    questions: Collection[str],
    max_rank: int,
) -> tuple[Pick, ...]:
    """Up to `per_kind` picks per kind, kinds in the order given; raises if any kind has none."""
    if per_kind < 1:
        raise ValueError("per_kind must be at least 1")
    eligible: dict[SourceId, tuple[SourceEntry, str]] = {}
    for entry in entries:
        if entry.split is not CorpusSplit.DEV:
            continue
        question = _question(entry, questions, max_rank)
        if question is not None:
            eligible[entry.source_id] = (entry, question)
    by_kind = {
        kind: [s for s, (e, _) in eligible.items() if any(c.kind is kind for c in e.candidates)]
        for kind in kinds
    }
    scarcity = {kind: (len(by_kind[kind]), i) for i, kind in enumerate(kinds)}
    assigned: dict[OverstatedReason, list[SourceId]] = {kind: [] for kind in kinds}
    for source_id, (entry, _) in eligible.items():
        own = [kind for kind in kinds if any(c.kind is kind for c in entry.candidates)]
        if own:
            assigned[min(own, key=scarcity.__getitem__)].append(source_id)
    picks: list[Pick] = []
    problems: list[str] = []
    for kind in kinds:
        chosen: list[Pick] = []
        clusters: set[SourceId] = set()
        for source_id in sorted(assigned[kind], key=_order):
            entry, question = eligible[source_id]
            if entry.cluster_id in clusters:
                continue
            clusters.add(entry.cluster_id)
            chosen.append(
                Pick(
                    kind=kind,
                    source_id=source_id,
                    question_id=question,
                    abstract_sha256=entry.abstract_sha256,
                )
            )
            if len(chosen) == per_kind:
                break
        if not chosen:
            problems.append(f"{kind.value}: no eligible dev source")
        picks.extend(chosen)
    if problems:
        raise TrapSamplingError(problems)
    return tuple(picks)
