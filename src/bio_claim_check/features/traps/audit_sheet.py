"""[RING:features/traps] The trap audit sheet: every drafted candidate, one decision each, nothing edited.

Why: a model drafted the claims, so ground truth exists only once the author confirms them (ADR 0022).
The sheet lists every row that passed the validity gate, parents before their traps, with the abstract to
read against. It carries the draft file's sha256, so a sheet made for another draft cannot be applied, and
the author may change only `decision` and `reason`: an added, missing, duplicated or edited row is
refused, and so is a row whose abstract no longer hashes to its sealed `abstract_sha256` (the decision
was made against the real abstract, without this module ever holding it). A trap is confirmed only with
its parent; a rejected parent drops its traps. No model rationale is shown (the draft has none), so the
author judges the claim, not the writer's argument.
The author checks: the parent is fully supported and not a close paraphrase of a sentence; a model trap
commits its kind and only its kind; a rule-floor trap changes what the parent states.
A model panel (ADR 0023) fills one copy of the same sheet per rater; each copy passes the same checks.
Must not: read files (abstracts are passed in), or decide anything itself.

No LLM is involved in this module.
"""

import csv
import hashlib
import io
from collections.abc import Mapping, Sequence
from typing import Final, Literal, Self

from pydantic import ValidationError, model_validator

from bio_claim_check.common.errors import BccError
from bio_claim_check.common.models import NonBlankStr, Sha256Hex, ValidatedModel
from bio_claim_check.common.text import CleanedText
from bio_claim_check.features.contracts.ids import ClaimId, SourceId
from bio_claim_check.features.traps.models import Confirmer, DraftRow, TrapItem, expected_truth

COLUMNS: Final[tuple[str, ...]] = (
    "draft_sha256",
    "id",
    "pair_id",
    "role",
    "kind",
    "generator",
    "rule",
    "source_id",
    "claim",
    "abstract",
    "decision",
    "reason",
)
_FIXED: Final = ("draft_sha256", "pair_id", "role", "kind", "generator", "rule", "source_id", "claim")
_FORMULA_START: Final = ("=", "+", "-", "@", "\t", "\r")


class TrapAuditError(BccError):
    """A filled-in trap sheet broke the audit rules. `problems` holds one line per problem."""

    code = "traps.audit_sheet"

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = tuple(problems)


class TrapDecision(ValidatedModel):
    id: ClaimId
    decision: Literal["confirm", "reject"]
    reason: NonBlankStr | None

    @model_validator(mode="after")
    def _reject_says_why(self) -> Self:
        if self.decision == "reject" and self.reason is None:
            raise ValueError("a rejection must say why")
        return self


def _cell(text: str) -> str:
    """Stop a spreadsheet from running text as a formula; the sheet compares escaped cells."""
    return "'" + text if text.startswith(_FORMULA_START) else text


def _shows(cell: str, abstract_sha256: str) -> bool:
    """Whether a cell is the sealed abstract, as written (formula-escaped or not)."""
    shown = {cell, cell[1:]} if cell.startswith("'") else {cell}
    return any(hashlib.sha256(text.encode()).hexdigest() == abstract_sha256 for text in shown)


def candidates(rows: Sequence[DraftRow]) -> tuple[DraftRow, ...]:
    """The rows the author decides: gate-passing rows whose parent also passed, parent first in each pair."""
    parents = {r.id for r in rows if r.role == "parent" and r.candidate}
    keep = [r for r in rows if r.candidate and r.pair_id in parents]
    return tuple(sorted(keep, key=lambda r: (r.pair_id, r.role != "parent", r.rule or "", r.id)))


def _fixed(row: DraftRow, draft_sha256: str) -> dict[str, str]:
    return {
        "draft_sha256": draft_sha256,
        "pair_id": row.pair_id,
        "role": row.role,
        "kind": row.kind.value,
        "generator": row.generator,
        "rule": row.rule or "",
        "source_id": row.source_id,
        "claim": _cell(row.claim or ""),
    }


def sheet_csv(
    rows: Sequence[DraftRow], draft_sha256: Sha256Hex, abstracts: Mapping[SourceId, CleanedText]
) -> str:
    """The sheet to fill in: one row per candidate, decision and reason blank."""
    out = io.StringIO()
    writer: csv.DictWriter[str] = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in candidates(rows):
        writer.writerow(
            {
                **_fixed(row, draft_sha256),
                "id": row.id,
                "abstract": _cell(abstracts[row.source_id]),
                "decision": "",
                "reason": "",
            }
        )
    return out.getvalue()


def parse_decisions(
    csv_text: str, rows: Sequence[DraftRow], draft_sha256: Sha256Hex
) -> tuple[TrapDecision, ...]:
    """Read a filled-in sheet made from exactly these rows; decisions come back in candidate order."""
    reader = csv.DictReader(io.StringIO(csv_text))
    missing_columns = [c for c in COLUMNS if c not in (reader.fieldnames or ())]
    if missing_columns:
        raise TrapAuditError([f"missing column(s): {', '.join(missing_columns)}"])
    cells_by_line = list(enumerate(reader, start=2))
    bound = {(cells["draft_sha256"] or "").strip() for _, cells in cells_by_line}
    if bound - {draft_sha256}:
        raise TrapAuditError(
            [f"this sheet was not made from draft {draft_sha256} (it names {sorted(bound)})"]
        )
    expected = {r.id: r for r in candidates(rows)}
    problems: list[str] = []
    seen: set[str] = set()
    decided: dict[str, TrapDecision] = {}
    for line, cells in cells_by_line:
        row_id = (cells["id"] or "").strip()
        row = expected.get(row_id)
        if row is None:
            problems.append(f"line {line}: {row_id or '(blank)'} is not a candidate of this draft")
            continue
        if row_id in seen:
            problems.append(f"line {line}: {row_id} is decided twice")
            continue
        seen.add(row_id)
        edited = [k for k, v in _fixed(row, draft_sha256).items() if (cells[k] or "") != v]
        if not _shows(cells["abstract"] or "", row.abstract_sha256):
            edited.append("abstract")
        if edited:
            problems.append(f"line {line}: {row_id}: edited column(s) {', '.join(edited)}")
            continue
        try:
            decided[row_id] = TrapDecision.model_validate(
                {
                    "id": row_id,
                    "decision": (cells["decision"] or "").strip().lower(),
                    "reason": (cells["reason"] or "").strip() or None,
                }
            )
        except ValidationError as err:
            message = "; ".join(e["msg"] for e in err.errors(include_input=False, include_url=False))
            problems.append(f"line {line}: {row_id}: {message}")
    problems.extend(f"{i} has no row (every candidate must be decided)" for i in expected if i not in seen)
    if problems:
        raise TrapAuditError(problems)
    return tuple(decided[i] for i in expected)


def confirmed_items(
    rows: Sequence[DraftRow], decisions: Sequence[TrapDecision], confirmed_by: Confirmer = "author"
) -> tuple[TrapItem, ...]:
    """The committed set: confirmed rows whose parent is confirmed too, sorted by id (I76)."""
    confirmed = {d.id for d in decisions if d.decision == "confirm"}
    return tuple(
        sorted(
            (
                _item(r, confirmed_by)
                for r in candidates(rows)
                if r.id in confirmed and r.pair_id in confirmed
            ),
            key=lambda i: i.id,
        )
    )


def _item(r: DraftRow, confirmed_by: Confirmer) -> TrapItem:
    disposition, label, reason = expected_truth(r.role, r.generator, r.kind)
    return TrapItem(
        id=r.id,
        pair_id=r.pair_id,
        role=r.role,
        kind=r.kind,
        question_id=r.question_id,
        source_id=r.source_id,
        abstract_sha256=r.abstract_sha256,
        claim=r.claim or "",
        expected_disposition=disposition,
        expected_label=label,
        expected_reason=reason,
        generator=r.generator,
        rule=r.rule,
        origin="model",
        origin_id=r.origin_id,
        confirmed_by=confirmed_by,
    )
