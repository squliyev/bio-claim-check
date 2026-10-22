"""[RING:features/corpus] The audit sheet: which candidates the author reads, in what order, with what call.

Why: the sieve only proposes candidates. Sieve precision is reported with a Wilson interval, which is
valid only if the reviewed rows are fixed in advance, not chosen by whoever reads them. So the order is a
public salted hash and the sheet must hold exactly the first N candidates: no gap, no extra row, no
duplicate, and every rejection says why (invariant I42). Code enforces this, not discipline.
Must not: read files or the cache (the caller passes abstracts in), or decide anything itself.

No LLM is involved in this module.
"""

import csv
import hashlib
import io
from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from pydantic import ValidationError

from bio_claim_check.common.errors import BccError
from bio_claim_check.common.text import CleanedText
from bio_claim_check.features.contracts.corpus import AuditDecision, CorpusSplit, SourceEntry
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.labels import OverstatedReason

COLUMNS: Final = ("position", "source_id", "rule", "evidence", "abstract", "decision", "reason")
_FORMULA_START: Final = ("=", "+", "-", "@", "\t", "\r")


class AuditSheetError(BccError):
    """A filled-in sheet broke the audit rules. `problems` holds one line per problem."""

    code = "corpus.audit_sheet"

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = tuple(problems)


def audit_order(source_ids: Iterable[SourceId], kind: OverstatedReason, salt: str) -> list[SourceId]:
    """The public review order: ascending sha256 of `salt:kind:source_id`, ties broken by the id."""

    def key(s: SourceId) -> tuple[str, str]:
        return hashlib.sha256(f"{salt}:{kind.value}:{s}".encode()).hexdigest(), s

    return sorted(set(source_ids), key=key)


def audit_ids(
    entries: Iterable[SourceEntry], split: CorpusSplit, kind: OverstatedReason, *, salt: str, n: int
) -> list[SourceId]:
    """The first `min(n, candidates)` candidates of one kind in one split, in the public order."""
    if n < 1:
        raise ValueError("n must be at least 1")
    pool = [e.source_id for e in entries if e.split is split and any(c.kind is kind for c in e.candidates)]
    return audit_order(pool, kind, salt)[:n]


def _cell(text: str) -> str:
    """Stop a spreadsheet from running abstract text as a formula; the cell is display-only."""
    return "'" + text if text.startswith(_FORMULA_START) else text


def sheet_csv(
    entries: Iterable[SourceEntry],
    ids: Sequence[SourceId],
    kind: OverstatedReason,
    abstracts: Mapping[SourceId, CleanedText],
) -> str:
    """The sheet to fill in: one row per id in order, with the sieve's evidence and the cleaned abstract."""
    by_id = {e.source_id: e for e in entries}
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for position, source_id in enumerate(ids, start=1):
        candidate = next(c for c in by_id[source_id].candidates if c.kind is kind)
        abstract = abstracts[source_id]
        if candidate.span is not None:
            evidence = candidate.span.of(abstract)
        else:
            evidence = "; ".join((*candidate.mesh, *candidate.publication_types))
        writer.writerow((position, source_id, candidate.rule, _cell(evidence), _cell(abstract), "", ""))
    return out.getvalue()


def parse_decisions(csv_text: str, expected: Sequence[SourceId]) -> tuple[AuditDecision, ...]:
    """Read a filled-in sheet: rows must be exactly `expected` (any order); returned in `expected` order."""
    reader = csv.DictReader(io.StringIO(csv_text))
    missing_columns = [c for c in ("source_id", "decision", "reason") if c not in (reader.fieldnames or ())]
    if missing_columns:
        raise AuditSheetError([f"missing column(s): {', '.join(missing_columns)}"])
    wanted = set(expected)
    problems: list[str] = []
    decided: dict[str, AuditDecision] = {}
    seen: set[str] = set()
    for line, row in enumerate(reader, start=2):
        source_id = (row["source_id"] or "").strip()
        if source_id not in wanted:
            problems.append(f"line {line}: {source_id or '(blank)'} is not one of the first {len(expected)}")
            continue
        if source_id in seen:
            problems.append(f"line {line}: {source_id} is decided twice")
            continue
        seen.add(source_id)
        decision = (row["decision"] or "").strip().lower()
        reason = (row["reason"] or "").strip() or None
        try:
            decided[source_id] = AuditDecision.model_validate(
                {"source_id": source_id, "decision": decision, "reason": reason}
            )
        except ValidationError as err:
            message = "; ".join(e["msg"] for e in err.errors(include_input=False, include_url=False))
            problems.append(f"line {line}: {source_id}: {message}")
    problems.extend(
        f"{s} has no row (the first {len(expected)} must all be decided)" for s in expected if s not in seen
    )
    if problems:
        raise AuditSheetError(problems)
    return tuple(decided[s] for s in expected)
