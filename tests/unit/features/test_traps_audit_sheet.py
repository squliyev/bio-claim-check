"""The trap audit sheet: bound to its draft, every candidate decided, nothing edited, parents gate traps."""

import csv
import io

import pytest
from tests.support.traps import parent, trap

from bio_claim_check.common.text import CleanedText
from bio_claim_check.features.contracts.labels import FailureKind
from bio_claim_check.features.traps.audit_sheet import (
    COLUMNS,
    TrapAuditError,
    candidates,
    confirmed_items,
    parse_decisions,
    sheet_csv,
)

SHA = "c" * 64
ROWS = (
    parent("MED:1"),
    trap("MED:1"),
    trap("MED:1", "Drug X raised plaque in mice.", rule="direction"),
    parent("MED:2", "-Y helped rats."),
    trap("MED:2", "Y helps people."),
    parent("MED:3", problems=("too long",)),
    trap("MED:3"),
    parent("MED:4", None, failure=FailureKind.STRUCTURED_OUTPUT),
    trap("MED:5", problems=("copies",)),
)
ABSTRACTS = {f"MED:{n}": CleanedText(f"=abstract {n}") for n in range(1, 6)}


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _fill(text: str, decide: dict[str, tuple[str, str]]) -> str:
    rows = _rows(text)
    out = io.StringIO()
    writer: csv.DictWriter[str] = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        decision, reason = decide.get(row["id"], ("confirm", ""))
        writer.writerow({**row, "decision": decision, "reason": reason})
    return out.getvalue()


def test_only_gated_rows_with_a_gated_parent_are_candidates_parent_first() -> None:
    kept = candidates(ROWS)
    assert {r.source_id for r in kept} == {"MED:1", "MED:2"}
    assert [r.role for r in kept if r.source_id == "MED:1"] == ["parent", "trap", "trap"]


def test_the_sheet_is_bound_to_the_draft_and_escapes_formulas() -> None:
    rows = _rows(sheet_csv(ROWS, SHA, ABSTRACTS))
    assert len(rows) == 5
    assert {r["draft_sha256"] for r in rows} == {SHA}
    assert all(r["abstract"].startswith("'=") for r in rows)
    assert any(r["claim"] == "'-Y helped rats." for r in rows)
    assert all(r["decision"] == "" for r in rows)


def test_a_complete_sheet_gives_confirmed_items_and_a_rejected_parent_drops_its_traps() -> None:
    sheet = sheet_csv(ROWS, SHA, ABSTRACTS)
    p2 = parent("MED:2").id
    floor = trap("MED:1", rule="direction").id
    filled = _fill(sheet, {p2: ("reject", "not supported"), floor: ("reject", "meaningless swap")})
    decisions = parse_decisions(filled, ROWS, SHA)
    assert len(decisions) == 5
    items = confirmed_items(ROWS, decisions)
    assert {(i.source_id, i.role, i.generator) for i in items} == {
        ("MED:1", "parent", "model"),
        ("MED:1", "trap", "model"),
    }
    assert [i.id for i in items] == sorted(i.id for i in items)
    assert all(i.confirmed_by == "author" and i.origin == "model" for i in items)


def _problems(text: str, sha: str = SHA) -> tuple[str, ...]:
    with pytest.raises(TrapAuditError) as err:
        parse_decisions(text, ROWS, sha)
    return err.value.problems


def test_another_drafts_sheet_is_refused() -> None:
    filled = _fill(sheet_csv(ROWS, "d" * 64, ABSTRACTS), {})
    (problem,) = _problems(filled)
    assert "not made from draft" in problem


def test_an_edited_claim_is_refused() -> None:
    filled = _fill(sheet_csv(ROWS, SHA, ABSTRACTS), {}).replace("Y helps people.", "Y helps everyone.")
    assert any("edited column(s) claim" in p for p in _problems(filled))


def test_added_duplicated_missing_and_undecided_rows_are_refused() -> None:
    filled = _fill(sheet_csv(ROWS, SHA, ABSTRACTS), {})
    lines = filled.splitlines(keepends=True)
    extra = lines[1].replace(parent("MED:1").id, "tffffffffff0")
    problems = _problems(lines[0] + lines[1] + lines[1] + extra + "".join(lines[3:]))
    assert any("decided twice" in p for p in problems)
    assert any("not a candidate" in p for p in problems)
    assert any("has no row" in p for p in problems)
    undecided = _fill(sheet_csv(ROWS, SHA, ABSTRACTS), {trap("MED:2").id: ("", "")})
    assert len(_problems(undecided)) == 1
    unreasoned = _fill(sheet_csv(ROWS, SHA, ABSTRACTS), {trap("MED:2").id: ("reject", "")})
    assert any("say why" in p for p in _problems(unreasoned))


def test_missing_columns_are_refused() -> None:
    assert _problems("id,decision\n") == (
        "missing column(s): draft_sha256, pair_id, role, kind, generator, rule, source_id, claim, reason",
    )
