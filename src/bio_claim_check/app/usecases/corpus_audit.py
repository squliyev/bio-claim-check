"""[RING:app/usecases] The author's sieve-precision audit: export a sheet, then record the decisions.

Why here: it combines the corpus slice (public order, sheet, parsing), bench (the Wilson interval) and
retrieval (abstracts replayed from the cache), and only `app` may combine slices (ADR 0002).
A test sheet holds test-abstract text, so it exists only under the active prompt freeze (ADR 0011, 0020,
I74): the caller recomputes the freeze hash, the sheet's first line carries it with the seal, and apply
checks both and records the freeze hash as `prompts_sha256`. A dev audit is unchanged (typed hash, no
header line). Each sheet lists only its own split's sources; its abstracts may come from any question's
cached pool, because the replay keeps only the wanted source ids.
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

_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_TEST_HEADER: Final = "# test audit; corpus_seal={seal}; freeze_sha256={freeze}\n"


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


def _test_header(files: Mapping[str, bytes], freeze_sha256: str) -> str:
    return _TEST_HEADER.format(seal=sha256_hex(files[MANIFEST]), freeze=freeze_sha256)


def _intact_entries(
    files: Mapping[str, bytes],
    spec: CorpusSpec,
    kind: OverstatedReason,
    split: CorpusSplit,
    freeze_sha256: str | None,
) -> list[SourceEntry]:
    if (split is CorpusSplit.TEST) != (freeze_sha256 is not None):
        raise AuditInputError(["a test audit needs the active prompt freeze, and only a test audit uses it"])
    if kind not in spec.trap_kinds:
        raise AuditInputError([f"{kind.value} is not a trap kind of this corpus"])
    if problems := dataset_problems(files, spec):
        raise AuditInputError(["the dataset is not intact and sealed:", *problems])
    lines = files[sources_file(split)].decode("utf-8").splitlines()
    return [SourceEntry.model_validate_json(line) for line in lines]


def export_sheet(
    files: Mapping[str, bytes],
    spec: CorpusSpec,
    kind: OverstatedReason,
    source: BaseLiteratureSource,
    *,
    split: CorpusSplit = CorpusSplit.DEV,
    freeze_sha256: str | None = None,
) -> str:
    """The audit sheet of `split` for `kind`: the first `audit_n` candidates in the public order.

    Abstracts come from replaying the build's own searches through `source` (read-only cache), the
    split's own questions first; each must still hash to the dataset's `abstract_sha256`, or the export is
    refused. A test sheet needs `freeze_sha256` (recomputed by the caller) and starts with a header line.
    """
    entries = _intact_entries(files, spec, kind, split, freeze_sha256)
    ids = audit_ids(entries, split, kind, salt=spec.audit_salt, n=spec.audit_n)
    if not ids:
        raise AuditInputError([f"no {split.value} candidates of {kind.value}"])
    by_id = {e.source_id: e for e in entries}
    wanted = set(ids)
    needed = {r.question_id for s in ids for r in by_id[s].ranks}
    ordered = sorted((q for q in spec.questions if q.id in needed), key=lambda q: q.split is not split)
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
    sheet = sheet_csv(entries, ids, kind, abstracts)
    return sheet if freeze_sha256 is None else _test_header(files, freeze_sha256) + sheet


def apply_decisions(
    files: Mapping[str, bytes],
    spec: CorpusSpec,
    kind: OverstatedReason,
    sheet: str,
    *,
    prompts_sha256: str,
    split: CorpusSplit = CorpusSplit.DEV,
) -> AuditSummary:
    """Check a filled-in sheet against the public order and build the record bound to the seal.

    For test, `prompts_sha256` is the recomputed active freeze hash, and the sheet's header line must name
    it and the current seal.
    """
    if not _SHA256.fullmatch(prompts_sha256):
        raise AuditInputError(["the prompts hash must be 64 lowercase hex characters"])
    freeze_sha256 = prompts_sha256 if split is CorpusSplit.TEST else None
    entries = _intact_entries(files, spec, kind, split, freeze_sha256)
    if freeze_sha256 is not None:
        header = _test_header(files, freeze_sha256)
        if not sheet.startswith(header):
            raise AuditInputError(["the sheet was not exported under this seal and the active prompt freeze"])
        sheet = sheet.removeprefix(header)
    expected = audit_ids(entries, split, kind, salt=spec.audit_salt, n=spec.audit_n)
    if not expected:
        raise AuditInputError([f"no {split.value} candidates of {kind.value}"])
    decisions = parse_decisions(sheet, expected)
    record = AuditRecord(
        split=split,
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
