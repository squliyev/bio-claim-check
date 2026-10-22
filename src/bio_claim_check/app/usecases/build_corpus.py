"""[RING:app/usecases] Build the evaluation corpus: pools, sieve, clusters, split and manifest (ADR 0010).

Why: the corpus needs retrieval (the pools) and the corpus slice (sieve, clusters, serialisation).
Slices never import each other, so only app may combine them. The whole build is deterministic: the
same spec, the same cached responses, the same tool version and the same declared fetch date give the
same bytes (invariant I37). The order of questions in the spec does not change the data files; the rank
order of each pool does, because ranks are data.
It distrusts its port: if one source comes back with different metadata under two questions, the build
stops instead of guessing which one is true.
Must not: do I/O (the caller publishes the bytes, manifest last), read the clock (the fetch date is
declared by the caller), or top up a short pool (a shortfall is reported, never fixed; ADR 0010 D6).

No LLM is involved in this module.
"""

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date

from bio_claim_check.features.contracts.corpus import (
    NLM_NOTICE,
    CorpusManifest,
    CorpusSpec,
    CorpusSplit,
    FileHash,
    QuestionEntry,
    QuestionRank,
    SourceEntry,
)
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.corpus.clusters import assign_splits, clusters, id_order
from bio_claim_check.features.corpus.eligibility import candidates, exclusions
from bio_claim_check.features.corpus.layout import (
    DEV_SOURCES,
    QUESTIONS,
    TEST_SOURCES,
    candidate_counts,
)
from bio_claim_check.features.corpus.serialise import (
    abstract_sha256,
    document_bytes,
    jsonl_bytes,
    model_sha256,
    pool_sha256,
    sha256_hex,
)
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource


class PoolConflictError(Exception):
    """One source came back with different metadata under two questions; the build cannot pick one."""


@dataclass(frozen=True, slots=True)
class CorpusFiles:
    """The dataset as bytes, keyed by path relative to the dataset folder. `manifest` is published last."""

    data: Mapping[str, bytes]
    manifest: bytes


def pool_query(search: str, cutoff: date) -> str:
    """The search sent for one question: its own search string, limited to papers published by `cutoff`."""
    return f"({search}) AND FIRST_PDATE:[1900-01-01 TO {cutoff.isoformat()}]"


def build_corpus(
    spec: CorpusSpec,
    source: BaseLiteratureSource,
    *,
    declared_fetched_on: date,
    tool_version: str,
    spec_file_sha256: str,
    response_sha256: Callable[[str, int], str],
) -> CorpusFiles:
    """Fetch every question's pool (in spec order, so cache keys are stable) and build the dataset bytes.

    `spec_file_sha256` hashes the spec file as committed; `response_sha256(query, limit)` gives the hash of
    the raw response behind a search already made, so others can check they fetched the same bytes.
    """
    pools = {
        q.id: source.search(pool_query(q.search, spec.cutoff), limit=spec.pool_hits) for q in spec.questions
    }

    papers: dict[SourceId, Paper] = {}
    ranks: dict[SourceId, list[QuestionRank]] = defaultdict(list)
    for question_id, pool in pools.items():
        for rank, paper in enumerate(pool, start=1):
            if papers.setdefault(paper.source_id, paper) != paper:
                raise PoolConflictError(f"{paper.source_id} differs between two questions' results")
            ranks[paper.source_id].append(QuestionRank(question_id=question_id, rank=rank))

    held_out = spec.held_out_domain()
    held_out_sources = {p.source_id for q in spec.questions if q.domain == held_out for p in pools[q.id]}
    cluster_of = clusters(papers.values())
    split_of = assign_splits(
        cluster_of, held_out_sources, salt=spec.split_salt, dev_fraction=spec.dev_fraction
    )

    entries = [
        SourceEntry(
            source_id=sid,
            year=paper.year,
            ranks=tuple(sorted(ranks[sid], key=lambda r: r.question_id)),
            cluster_id=cluster_of[sid],
            split=split_of[sid],
            retracted=paper.retracted,
            publication_types=paper.publication_types,
            mesh_headings=paper.mesh_headings,
            abstract_sha256=abstract_sha256(paper),
            never_because=exclusions(paper),
            candidates=candidates(paper, spec.trap_kinds),
        )
        for sid, paper in sorted(papers.items(), key=lambda item: id_order(item[0]))
    ]
    questions = [
        QuestionEntry.model_validate(
            {
                **q.model_dump(),
                "query": pool_query(q.search, spec.cutoff),
                "response_sha256": response_sha256(pool_query(q.search, spec.cutoff), spec.pool_hits),
                "pool_size": len(pools[q.id]),
                "split_pool_size": sum(split_of[p.source_id] is q.split for p in pools[q.id]),
                "pool_sha256": pool_sha256([(p.source_id, abstract_sha256(p)) for p in pools[q.id]]),
            }
        )
        for q in sorted(spec.questions, key=lambda q: q.id)
    ]
    data = {
        DEV_SOURCES: jsonl_bytes(e for e in entries if e.split is CorpusSplit.DEV),
        TEST_SOURCES: jsonl_bytes(e for e in entries if e.split is CorpusSplit.TEST),
        QUESTIONS: jsonl_bytes(questions),
    }
    manifest = CorpusManifest(
        schema_version=1,
        tool_version=tool_version,
        declared_fetched_on=declared_fetched_on,
        spec_sha256=model_sha256(spec),
        spec_file_sha256=spec_file_sha256,
        notice=NLM_NOTICE,
        files=tuple(FileHash(name=n, sha256=sha256_hex(b)) for n, b in sorted(data.items())),
        candidate_counts=candidate_counts(spec, entries),
    )
    return CorpusFiles(data=data, manifest=document_bytes(manifest))
