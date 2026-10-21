"""[RING:features/corpus] Where each corpus file lives, and the candidate counts the manifest records.

Why: the build writes the dataset, the seal check reads it back, and the audit tooling adds to it. All
three must agree on one layout and one way of counting candidates, so both live here, not in the use
case that happened to need them first (they moved from `app/usecases/build_corpus.py` in S07b).
Must not: read or write files; paths here are relative names inside the dataset folder.

No LLM is involved in this module.
"""

from collections import defaultdict
from collections.abc import Iterable
from typing import Final

from bio_claim_check.features.contracts.corpus import CandidateCount, CorpusSpec, CorpusSplit, SourceEntry
from bio_claim_check.features.contracts.labels import OverstatedReason

SPEC: Final = "corpus.yaml"
DEV_SOURCES: Final = "dev/sources.jsonl"
TEST_SOURCES: Final = "test/sources.jsonl"
QUESTIONS: Final = "questions.jsonl"
MANIFEST: Final = "manifest.json"
SEALED: Final = "SEALED"
README: Final = "README.md"
DATA_FILES: Final = (DEV_SOURCES, QUESTIONS, TEST_SOURCES)
"""The files the manifest hashes, sorted by name."""


def sources_file(split: CorpusSplit) -> str:
    return DEV_SOURCES if split is CorpusSplit.DEV else TEST_SOURCES


def audit_file(split: CorpusSplit, kind: OverstatedReason) -> str:
    """Where the one audit record of a kind in a split lives."""
    return f"audit/{split.value}/{kind.value}.json"


def candidate_counts(spec: CorpusSpec, entries: Iterable[SourceEntry]) -> tuple[CandidateCount, ...]:
    """Candidates per domain, split and kind, zeros included, so a shortfall is visible, not missing.

    A source retrieved by questions from two domains counts once in each domain.
    """
    domain_of_question = {q.id: q.domain for q in spec.questions}
    n: defaultdict[tuple[str, CorpusSplit, str], int] = defaultdict(int)
    for e in entries:
        for domain in {domain_of_question[r.question_id] for r in e.ranks}:
            for c in e.candidates:
                n[(domain, e.split, c.kind)] += 1
    return tuple(
        CandidateCount(domain=d.id, split=split, kind=kind, n=n[(d.id, split, kind)])
        for d in sorted(spec.domains, key=lambda d: d.id)
        for split in CorpusSplit
        for kind in spec.trap_kinds
    )
