"""[RING:features/corpus] Cluster papers that report the same trial, and split clusters into dev and test.

Why: splitting by PMID alone puts a trial's main paper in test and its secondary analysis in dev, so
tuning on dev would quietly see test findings. Papers sharing a trial registry id (NCT) or a normalised
title are joined (union-find, so A-B by NCT and B-C by title is one cluster), and the whole cluster goes
to one split. A cluster touching the held-out domain is always test. Every other cluster is placed by a
public salted hash of its smallest id, so anyone can recompute the split and nobody can steer it.
Must not: read randomness or the clock, or look at labels or candidates when splitting.

No LLM is involved in this module.
"""

import hashlib
import re
from collections.abc import Iterable, Mapping
from typing import Final

from bio_claim_check.features.contracts.corpus import CorpusSplit
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.paper import Paper

NCT_ID: Final = re.compile(r"\bNCT\d{8}\b", re.IGNORECASE)
_NOT_ALNUM: Final = re.compile(r"[\W_]+")


def registry_ids(paper: Paper) -> frozenset[str]:
    """NCT ids in the title and cleaned abstract, upper-cased (`nct01234567` = `NCT01234567`)."""
    return frozenset(m.upper() for text in (paper.title, paper.abstract) for m in NCT_ID.findall(text))


def title_key(title: str) -> str:
    """Casefolded alphanumerics only, so punctuation, spacing and case differences still match."""
    return _NOT_ALNUM.sub("", title.casefold())


def id_order(source_id: SourceId) -> tuple[str, int, int, str]:
    """Numeric order within a namespace (`MED:9` before `MED:10`), so "smallest id" means smallest PMID."""
    namespace, _, local = source_id.partition(":")
    return (namespace, 0, int(local), "") if local.isdigit() else (namespace, 1, 0, local)


def clusters(papers: Iterable[Paper]) -> dict[SourceId, SourceId]:
    """source_id → cluster id (the smallest member id); papers sharing an NCT id or title key are joined."""
    parent: dict[SourceId, SourceId] = {}

    def find(x: SourceId) -> SourceId:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: SourceId, b: SourceId) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            low, high = sorted((ra, rb), key=id_order)
            parent[high] = low

    first_with: dict[str, SourceId] = {}
    for paper in papers:
        parent.setdefault(paper.source_id, paper.source_id)
        keys = {f"nct:{n}" for n in registry_ids(paper)}
        if key := title_key(paper.title):
            keys.add(f"title:{key}")
        for k in sorted(keys):
            if k in first_with:
                union(first_with[k], paper.source_id)
            else:
                first_with[k] = paper.source_id
    return {source_id: find(source_id) for source_id in parent}


def hash_fraction(salt: str, cluster_id: SourceId) -> float:
    """A public, uniform-looking number in [0, 1) for one cluster: the first 64 bits of a salted sha256."""
    digest = hashlib.sha256(f"{salt}:{cluster_id}".encode()).hexdigest()
    return int(digest[:16], 16) / 2**64


def assign_splits(
    cluster_of: Mapping[SourceId, SourceId],
    held_out_sources: Iterable[SourceId],
    *,
    salt: str,
    dev_fraction: float,
) -> dict[SourceId, CorpusSplit]:
    """Split per source, decided per cluster: held-out clusters → test, the rest by `hash_fraction`."""
    held_out_clusters = {cluster_of[s] for s in held_out_sources}
    split_of_cluster = {
        c: CorpusSplit.TEST
        if c in held_out_clusters or hash_fraction(salt, c) >= dev_fraction
        else CorpusSplit.DEV
        for c in set(cluster_of.values())
    }
    return {s: split_of_cluster[c] for s, c in cluster_of.items()}
