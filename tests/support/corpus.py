"""[TEST SUPPORT] A fictional corpus world: a query-keyed literature source and the pools it serves.

`InMemoryLiteratureSource` ignores the query, but the corpus build sends one query per question, so
this source maps each exact query string to its ranked papers and records every call. The world is
built to exercise every corpus rule: a paper retrieved by two questions, an NCT id linking a dev-domain
paper to the held-out domain, a retracted paper and ids whose numeric and string orders differ.
"""

import hashlib
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import override

from bio_claim_check.app.container import load_corpus_spec
from bio_claim_check.app.usecases.build_corpus import CorpusFiles, build_corpus, pool_query
from bio_claim_check.common.text import Span
from bio_claim_check.features.contracts.corpus import (
    Candidate,
    CorpusSpec,
    CorpusSplit,
    QuestionRank,
    SourceEntry,
)
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.corpus.layout import MANIFEST, SPEC
from bio_claim_check.features.corpus.serialise import sha256_hex
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.retrieval.models import RetractionStatus
from tests.support.papers import paper

SPEC_FILE = Path(__file__).parents[1] / "fixtures" / "corpus" / "spec_valid.yaml"
CUTOFF = date(2024, 12, 31)
FETCHED = date(2025, 1, 15)


class QueryLiteratureSource(BaseLiteratureSource):
    """Serves fixed pools by exact query string; an unknown query returns no papers."""

    def __init__(self, pools: Mapping[str, tuple[Paper, ...]]) -> None:
        self._pools = dict(pools)
        self.calls: list[tuple[str, int]] = []

    @override
    def search(self, question: str, *, limit: int) -> tuple[Paper, ...]:
        self.calls.append((question, limit))
        return self._pools.get(question, ())[:limit]

    def response_sha256(self, question: str, limit: int) -> str:
        """A stand-in for the raw response hash: the ranked ids served, so a changed pool changes it."""
        served = " ".join(p.source_id for p in self._pools.get(question, ())[:limit])
        return hashlib.sha256(f"{question}|{limit}|{served}".encode()).hexdigest()

    @override
    def retraction_status(self, source_ids: Sequence[SourceId]) -> tuple[RetractionStatus, ...]:
        raise NotImplementedError  # never asked: these tests only search


ANIMAL = paper(1, mesh=("Animals", "Mice"))
COHORT = paper(2, mesh=("Humans", "Cohort Studies"))
STATIN_TRIAL = paper(3, abstract="We ran trial NCT01234567 in patients. The drug was tolerated.")
LINKED = paper(4, abstract="A secondary analysis of nct01234567 in patients. Results are reported.")
RETRACTED = paper(5, mesh=("Animals",), retracted=True)
NULL_RESULT = paper(10, abstract="Patients were randomised. The drug did not reduce decline.")
HEDGED = paper(11, abstract="Mice received the drug. Memory improved. These findings suggest a benefit.")


def world() -> dict[str, tuple[Paper, ...]]:
    """Ranked pools by query for the three questions in `spec_valid.yaml`."""
    return {
        pool_query("OS-912 AND decline", CUTOFF): (ANIMAL, COHORT, NULL_RESULT, RETRACTED, HEDGED),
        pool_query("OS-912 AND neurons", CUTOFF): (LINKED, ANIMAL),
        pool_query("HX-15 AND dementia", CUTOFF): (STATIN_TRIAL,),
    }


def source_entry(
    pmid: int,
    split: CorpusSplit = CorpusSplit.DEV,
    *,
    kinds: tuple[OverstatedReason, ...] = (OverstatedReason.PRECLINICAL_TO_CLINICAL,),
    span: Span | None = None,
    question: str = "a-q1",
) -> SourceEntry:
    """A valid source row; MeSH kinds carry MeSH evidence, text kinds the given span (default 0-8)."""
    mesh_kinds = {OverstatedReason.PRECLINICAL_TO_CLINICAL, OverstatedReason.CORRELATION_AS_CAUSATION}
    candidates = tuple(
        Candidate(kind=k, rule="animals_not_humans", mesh=("Animals",))
        if k in mesh_kinds
        else Candidate(kind=k, rule="null_result", span=span or Span(0, 8))
        for k in kinds
    )
    return SourceEntry(
        source_id=f"MED:{pmid}",
        year=2020,
        ranks=(QuestionRank(question_id=question, rank=1),),
        cluster_id=f"MED:{pmid}",
        split=split,
        retracted=False,
        publication_types=("Journal Article",),
        mesh_headings=("Animals",),
        abstract_sha256="a" * 64,
        never_because=(),
        candidates=candidates,
    )


def build(spec: CorpusSpec | None = None, source: QueryLiteratureSource | None = None) -> CorpusFiles:
    """The corpus built from `SPEC_FILE` over `world()`, with fixed date and tool version."""
    source = source or QueryLiteratureSource(world())
    return build_corpus(
        spec or load_corpus_spec(SPEC_FILE),
        source,
        declared_fetched_on=FETCHED,
        tool_version="0.0.0-test",
        spec_file_sha256=sha256_hex(SPEC_FILE.read_bytes()),
        response_sha256=source.response_sha256,
    )


def dataset_files() -> dict[str, bytes]:
    """Every file of an unsealed dataset folder built from `SPEC_FILE`, keyed by relative path."""
    files = build()
    return {**files.data, MANIFEST: files.manifest, SPEC: SPEC_FILE.read_bytes()}
