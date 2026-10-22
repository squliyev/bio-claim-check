"""[RING:app/usecases] The author's sieve-precision audit: export a sheet, then record the decisions.

Why here: it combines the corpus slice (public order, sheet, parsing), bench (the Wilson interval) and
retrieval (abstracts replayed from the cache), and only `app` may combine slices (ADR 0002).
Dev split only (S07b): a test sheet holds test-abstract text, so its export waits for the prompt-freeze
record of S12, which will recompute the prompt hash itself instead of trusting a flag.
Must not: touch the network (the caller passes a read-only source), write files (the CLI publishes
through the container), or run on a dataset that is not intact and sealed (I41, I42).
No LLM is involved in this module.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from bio_claim_check.app.usecases.build_corpus import pool_query
from bio_claim_check.common.errors import BccError
from bio_claim_check.common.text import CleanedText
from bio_claim_check.features.bench.stats import wilson
from bio_claim_check.features.contracts.corpus import (
    AuditRecord,
    CorpusSpec,
    CorpusSplit,
    SourceEntry,
)
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.corpus.audit_sheet import audit_ids, parse_decisions, sheet_csv
from bio_claim_check.features.corpus.layout import MANIFEST, sources_file
from bio_claim_check.features.corpus.seal import dataset_problems
from bio_claim_check.features.corpus.serialise import abstract_sha256, document_bytes, sha256_hex
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource

AUDIT_SPLIT: Final = CorpusSplit.DEV
_SHA256: Final = re.compile(r"[0-9a-f]{64}")


class AuditInputError(BccError):
    """The dataset, the kind or the cache cannot support this audit. `problems` holds one line each."""

    code = "corpus.audit_input"

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = tuple(problems)


@dataclass(frozen=True, slots=True)
class AuditSummary:
    """A validated record, ready to publish, and its precision with a 95 % Wilson interval."""

    record: bytes
    confirmed: int
    reviewed: int
    interval: tuple[float, float]


def _intact_dev_entries(
    files: Mapping[str, bytes], spec: CorpusSpec, kind: OverstatedReason
) -> list[SourceEntry]:
    if kind not in spec.trap_kinds:
        raise AuditInputError([f"{kind.value} is not a trap kind of this corpus"])
    if problems := dataset_problems(files, spec):
        raise AuditInputError(["the dataset is not intact and sealed:", *problems])
    lines = files[sources_file(AUDIT_SPLIT)].decode("utf-8").splitlines()
    return [SourceEntry.model_validate_json(line) for line in lines]


def export_sheet(
    files: Mapping[str, bytes], spec: CorpusSpec, kind: OverstatedReason, source: BaseLiteratureSource
) -> str:
    """The dev audit sheet for `kind`: the first `audit_n` candidates in the public order, with abstracts.

    Abstracts come from replaying the build's own searches through `source` (read-only cache), dev
    questions first; each must still hash to the dataset's `abstract_sha256`, or the export is refused.
    """
    entries = _intact_dev_entries(files, spec, kind)
    ids = audit_ids(entries, AUDIT_SPLIT, kind, salt=spec.audit_salt, n=spec.audit_n)
    if not ids:
        raise AuditInputError([f"no {AUDIT_SPLIT.value} candidates of {kind.value}"])
    by_id = {e.source_id: e for e in entries}
    wanted = set(ids)
    needed = {r.question_id for s in ids for r in by_id[s].ranks}
    ordered = sorted((q for q in spec.questions if q.id in needed), key=lambda q: q.split is not AUDIT_SPLIT)
    abstracts: dict[SourceId, CleanedText] = {}
    drifted: list[str] = []
    for question in ordered:
        if wanted <= abstracts.keys():
            break
        for paper in source.search(pool_query(question.search, spec.cutoff), limit=spec.pool_hits):
            if paper.source_id in wanted and paper.source_id not in abstracts:
                if abstract_sha256(paper) != by_id[paper.source_id].abstract_sha256:
                    drifted.append(f"{paper.source_id}: the cached abstract does not match the dataset")
                abstracts[paper.source_id] = paper.abstract
    missing = [f"{s}: not found in its questions' cached pools" for s in ids if s not in abstracts]
    if drifted or missing:
        raise AuditInputError(drifted + missing)
    return sheet_csv(entries, ids, kind, abstracts)


def apply_decisions(
    files: Mapping[str, bytes],
    spec: CorpusSpec,
    kind: OverstatedReason,
    sheet: str,
    *,
    prompts_sha256: str,
) -> AuditSummary:
    """Check a filled-in dev sheet against the public order and build the record bound to the seal."""
    if not _SHA256.fullmatch(prompts_sha256):
        raise AuditInputError(["the prompts hash must be 64 lowercase hex characters"])
    entries = _intact_dev_entries(files, spec, kind)
    expected = audit_ids(entries, AUDIT_SPLIT, kind, salt=spec.audit_salt, n=spec.audit_n)
    if not expected:
        raise AuditInputError([f"no {AUDIT_SPLIT.value} candidates of {kind.value}"])
    decisions = parse_decisions(sheet, expected)
    record = AuditRecord(
        split=AUDIT_SPLIT,
        kind=kind,
        corpus_seal=sha256_hex(files[MANIFEST]),
        prompts_sha256=prompts_sha256,
        decisions=decisions,
    )
    confirmed = sum(d.decision == "confirm" for d in decisions)
    return AuditSummary(
        record=document_bytes(record),
        confirmed=confirmed,
        reviewed=len(decisions),
        interval=wilson(confirmed, len(decisions)),
    )
