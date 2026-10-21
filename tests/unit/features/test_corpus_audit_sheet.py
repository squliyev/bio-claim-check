"""The audit sheet (I42): a public first-N order; only complete, reasoned decisions are accepted."""

import csv
import hashlib
import io

import pytest
from tests.support.corpus import source_entry

from bio_claim_check.common.text import CleanedText, Span
from bio_claim_check.features.contracts.corpus import CorpusSplit
from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.corpus.audit_sheet import (
    COLUMNS,
    AuditSheetError,
    audit_ids,
    audit_order,
    parse_decisions,
    sheet_csv,
)

PRE = OverstatedReason.PRECLINICAL_TO_CLINICAL
NULL = OverstatedReason.NONSIGNIFICANT_AS_EFFECT
SALT = "bio-claim-check/audit/v1"
IDS: list[str] = ["MED:3", "MED:1", "MED:22", "MED:4"]


def test_order_is_the_documented_salted_hash() -> None:
    expected = sorted(IDS, key=lambda s: hashlib.sha256(f"{SALT}:{PRE.value}:{s}".encode()).hexdigest())
    assert audit_order(IDS, PRE, SALT) == expected


def test_order_ignores_input_order_and_duplicates() -> None:
    assert audit_order([*reversed(IDS), IDS[0]], PRE, SALT) == audit_order(IDS, PRE, SALT)


def test_order_depends_on_salt_and_kind() -> None:
    many = [f"MED:{n}" for n in range(1, 40)]
    base = audit_order(many, PRE, SALT)
    assert audit_order(many, PRE, "other-salt") != base
    assert audit_order(many, NULL, SALT) != base


def test_audit_ids_take_the_first_n_candidates_of_one_kind_in_one_split() -> None:
    entries = [
        *(source_entry(n) for n in range(1, 8)),
        source_entry(50, CorpusSplit.TEST),
        source_entry(60, kinds=(NULL,)),
    ]
    dev_pre = [f"MED:{n}" for n in range(1, 8)]
    assert audit_ids(entries, CorpusSplit.DEV, PRE, salt=SALT, n=3) == audit_order(dev_pre, PRE, SALT)[:3]
    assert audit_ids(entries, CorpusSplit.DEV, PRE, salt=SALT, n=100) == audit_order(dev_pre, PRE, SALT)
    assert audit_ids(entries, CorpusSplit.TEST, PRE, salt=SALT, n=5) == ["MED:50"]
    assert audit_ids(entries, CorpusSplit.TEST, NULL, salt=SALT, n=5) == []


def test_audit_ids_need_n_at_least_one() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        audit_ids([], CorpusSplit.DEV, PRE, salt=SALT, n=0)


def rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_sheet_has_evidence_and_abstract_in_order_and_blank_decisions() -> None:
    entries = [source_entry(1), source_entry(2, kinds=(NULL,), span=Span(3, 10))]
    abstracts = {
        "MED:1": CleanedText("Mice got it."),
        "MED:2": CleanedText("We = found none."),
    }
    text = sheet_csv(entries, ["MED:2"], NULL, abstracts)
    assert text.splitlines()[0] == ",".join(COLUMNS)
    [row] = rows(text)
    assert row == {
        "position": "1",
        "source_id": "MED:2",
        "rule": "null_result",
        "evidence": "'= found",
        "abstract": "We = found none.",
        "decision": "",
        "reason": "",
    }
    [mesh_row] = rows(sheet_csv(entries, ["MED:1"], PRE, abstracts))
    assert mesh_row["evidence"] == "Animals"


def test_formula_like_cells_are_neutralised() -> None:
    entries = [source_entry(1)]
    for start in ("=", "+", "-", "@"):
        [row] = rows(sheet_csv(entries, ["MED:1"], PRE, {"MED:1": CleanedText(start + "1")}))
        assert row["abstract"] == "'" + start + "1"


EXPECTED: list[str] = ["MED:1", "MED:2"]


def sheet(*lines: str, header: str = "source_id,decision,reason") -> str:
    return "\n".join((header, *lines)) + "\n"


def test_complete_sheet_is_parsed_in_expected_order() -> None:
    got = parse_decisions(sheet("MED:2, Reject ,human data", "MED:1,confirm,"), EXPECTED)
    assert [(d.source_id, d.decision, d.reason) for d in got] == [
        ("MED:1", "confirm", None),
        ("MED:2", "reject", "human data"),
    ]


def test_a_sheet_exported_by_sheet_csv_round_trips_once_filled() -> None:
    entries = [source_entry(1), source_entry(2)]
    abstracts = {s: CleanedText("Mice, got it.") for s in EXPECTED}
    filled: list[dict[str, str]] = []
    for row in rows(sheet_csv(entries, EXPECTED, PRE, abstracts)):
        row["decision"] = "confirm"
        filled.append(row)
    out = io.StringIO()
    writer: csv.DictWriter[str] = csv.DictWriter(out, COLUMNS)
    writer.writeheader()
    writer.writerows(filled)
    assert [d.decision for d in parse_decisions(out.getvalue(), EXPECTED)] == ["confirm", "confirm"]


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        (sheet("MED:1,confirm,"), "MED:2 has no row"),
        (
            sheet("MED:1,confirm,", "MED:2,confirm,", "MED:3,confirm,"),
            "line 4: MED:3 is not one of the first 2",
        ),
        (sheet("MED:1,confirm,", "MED:1,reject,x", "MED:2,confirm,"), "line 3: MED:1 is decided twice"),
        (sheet("MED:1,confirm,", ",confirm,", "MED:2,confirm,"), "line 3: (blank) is not one of the first 2"),
        (sheet("MED:1,reject,", "MED:2,confirm,"), "line 2: MED:1:"),
        (sheet("MED:1,confirm,looks fine", "MED:2,confirm,"), "line 2: MED:1:"),
        (sheet("MED:1,maybe,", "MED:2,confirm,"), "line 2: MED:1:"),
        (sheet("MED:1,,", "MED:2,confirm,"), "line 2: MED:1:"),
        (sheet("MED:1,confirm", header="source_id,decision"), "missing column(s): reason"),
    ],
)
def test_broken_sheets_are_refused_with_a_named_problem(text: str, problem: str) -> None:
    with pytest.raises(AuditSheetError) as err:
        parse_decisions(text, EXPECTED)
    assert any(p.startswith(problem) for p in err.value.problems), err.value.problems


def test_a_duplicate_does_not_also_report_the_id_as_missing() -> None:
    with pytest.raises(AuditSheetError) as err:
        parse_decisions(sheet("MED:1,confirm,", "MED:1,confirm,", "MED:2,confirm,"), EXPECTED)
    assert err.value.problems == ("line 3: MED:1 is decided twice",)


def test_every_problem_is_reported_at_once() -> None:
    with pytest.raises(AuditSheetError) as err:
        parse_decisions(sheet("MED:9,confirm,", "MED:1,reject,"), EXPECTED)
    assert len(err.value.problems) == 3
