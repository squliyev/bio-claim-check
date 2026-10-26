"""[TEST SUPPORT] The predeclared rule that picks the H1 demo papers (demo/h1-protocol.md).

Why: the demo papers must be chosen by a rule fixed before any abstract is read, so nobody can pick papers
the verifier happens to get right. This module was committed before the picks were made; the arch test
re-runs it against `demo/h1-trap-papers.json`. It lives in tests, not `src`: it is a one-off protocol,
not product code (plan review finding 16).
Must not: read abstracts, call the network, or rank by anything but the public salted order.

No LLM is involved in this module.
"""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from bio_claim_check.features.contracts.corpus import CorpusSplit, SourceEntry
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.corpus.audit_sheet import audit_order

SHORTLIST: Final = 3
"""At most this many ordered candidates per kind are read; the first eligible one is the pick."""

KINDS: Final[tuple[tuple[OverstatedReason, str, str], ...]] = (
    (
        OverstatedReason.PRECLINICAL_TO_CLINICAL,
        "animals_not_humans",
        "animal or cell result stated for humans",
    ),
    (OverstatedReason.BACKGROUND_AS_RESULT, "prior_finding", "prior finding stated as this study's result"),
    (OverstatedReason.NONSIGNIFICANT_AS_EFFECT, "null_result", "null result stated as an effect"),
)
"""(kind, sieve rule, plain name). The IDEA's surrogate-endpoint example has no sieve kind, so the third
demo kind is a null result stated as an effect; it is never called a surrogate endpoint."""


def used_ids(entries: Iterable[SourceEntry], *jsonl_files: Path) -> frozenset[SourceId]:
    """Every `source_id` of earlier sets (challenge, traps) and the `cluster_id` each one has in
    `entries`: their verifier results are already known, and a cluster sibling is the same work."""
    sources: set[SourceId] = set()
    for path in jsonl_files:
        sources |= {json.loads(line)["source_id"] for line in path.read_text().splitlines() if line.strip()}
    return frozenset(sources | {e.cluster_id for e in entries if e.source_id in sources})


def shortlist(
    entries: Iterable[SourceEntry],
    kind: OverstatedReason,
    rule: str,
    *,
    salt: str,
    excluded: frozenset[SourceId],
) -> list[SourceEntry]:
    """The first `SHORTLIST` dev entries with a `rule` candidate of `kind`, in the public audit order,
    leaving out any entry whose source or cluster is in `excluded`."""
    pool = {
        e.source_id: e
        for e in entries
        if e.split is CorpusSplit.DEV
        and any(c.kind is kind and c.rule == rule for c in e.candidates)
        and not {e.source_id, e.cluster_id} & excluded
    }
    return [pool[s] for s in audit_order(pool, kind, salt)[:SHORTLIST]]
