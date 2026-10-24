"""The trap use cases (S13): dev only, budget first, every row kept, the verifier sees only the claim."""

import csv
import io
import json
from collections.abc import Mapping, Sequence
from typing import override

import pytest
from pydantic import ValidationError
from tests.support.corpus import SPEC_FILE, QueryLiteratureSource, dataset_files, world

from bio_claim_check.app.container import default_rulepack, load_corpus_spec
from bio_claim_check.app.usecases.traps import (
    SCORED_KINDS,
    TrapBudgetError,
    TrapInputError,
    TrapPoolError,
    TrapVerifyPorts,
    TrapWriterPorts,
    apply_audit,
    draft_bytes,
    generate,
    parse_draft,
    parse_set,
    result_problems,
    set_bytes,
    set_problems,
    sheet_for,
    trap_result_bytes,
    verify_set,
)
from bio_claim_check.common.model_family import ModelFamily
from bio_claim_check.engine.llm.model_spec import UnknownDeploymentError
from bio_claim_check.features.contracts.labels import Disposition, FailureKind, Label, OverstatedReason
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.rulepack import Rule, RulePack
from bio_claim_check.features.contracts.verdict import Claim, Verdict, VerifierFailure, VerifierOutput
from bio_claim_check.features.corpus.layout import DEV_SOURCES, MANIFEST, SEALED
from bio_claim_check.features.corpus.seal import sealed_bytes
from bio_claim_check.features.corpus.serialise import sha256_hex
from bio_claim_check.features.traps.audit_sheet import TrapAuditError
from bio_claim_check.features.traps.models import TrapDraft, TrapItem, TrapWriterFailure, opaque_id
from bio_claim_check.features.traps.sampling import TrapSamplingError
from bio_claim_check.features.traps.scripted_trap_writer import ScriptedTrapWriter
from bio_claim_check.features.verify.base_verifier import BaseVerifier
from bio_claim_check.features.verify.scripted_verifier import Script, ScriptedVerifier

pytestmark = pytest.mark.unit
SPEC = load_corpus_spec(SPEC_FILE)
PACK = default_rulepack()
KIND = OverstatedReason.CERTAINTY_INFLATION  # the fixture's one dev candidate (MED:11)
SOURCE = "MED:11"
WRITER = "writer-deployment"
PARENT = "Memory increased in treated mice."
TRAP = "The drug is proven to restore memory in mice."
DRAFT = TrapDraft(parent=PARENT, trap=TRAP)
PARENT_ID = opaque_id(SOURCE, "parent", None)
TRAP_ID = opaque_id(SOURCE, "trap", None)
FLOOR_ID = opaque_id(SOURCE, "trap", "direction")


def _sealed() -> dict[str, bytes]:
    files = dataset_files()
    return {**files, SEALED: sealed_bytes(files[MANIFEST])}


FILES = _sealed()


class CountingWriter(ScriptedTrapWriter):
    def __init__(self, script: dict[str, TrapDraft | FailureKind]) -> None:
        super().__init__(script)
        self.calls = 0

    @override
    def draft(self, kind: OverstatedReason, rule: Rule, paper: Paper) -> TrapDraft | TrapWriterFailure:
        self.calls += 1
        return super().draft(kind, rule, paper)


def _writer_ports(
    script: dict[str, TrapDraft | FailureKind] | None = None,
    pools: dict[str, tuple[Paper, ...]] | None = None,
) -> tuple[TrapWriterPorts, QueryLiteratureSource, CountingWriter]:
    source = QueryLiteratureSource(world() if pools is None else pools)
    writer = CountingWriter({SOURCE: DRAFT} if script is None else script)
    return TrapWriterPorts(literature=source, writer=writer, rules=PACK), source, writer


def _generate(ports: TrapWriterPorts, budget: int | None = 40, files: dict[str, bytes] = FILES) -> bytes:
    rows = generate(ports, files, SPEC, per_kind=1, origin_id=WRITER, max_live_calls=budget, kinds=(KIND,))
    return draft_bytes(rows)


def _decide(sheet: str, reject: frozenset[str] = frozenset()) -> str:
    reader = csv.DictReader(io.StringIO(sheet))
    out = io.StringIO()
    writer: csv.DictWriter[str] = csv.DictWriter(out, fieldnames=reader.fieldnames or (), lineterminator="\n")
    writer.writeheader()
    for row in reader:
        rejected = row["id"] in reject
        writer.writerow(
            {**row, "decision": "reject" if rejected else "confirm", "reason": "no" if rejected else ""}
        )
    return out.getvalue()


def _committed_set(reject: frozenset[str] = frozenset()) -> bytes:
    ports, source, _ = _writer_ports()
    draft = _generate(ports)
    return apply_audit(draft, _decide(sheet_for(source, draft, FILES, SPEC), reject), FILES, SPEC, PACK)


def test_one_draft_yields_a_parent_its_trap_and_the_floor_traps_of_the_parent() -> None:
    ports, source, writer = _writer_ports()
    rows = parse_draft(_generate(ports))
    assert writer.calls == 1
    assert len(source.calls) == 1  # one dev question, one search
    assert [(r.id, r.role, r.generator, r.rule) for r in rows] == [
        (PARENT_ID, "parent", "model", None),
        (TRAP_ID, "trap", "model", None),
        (FLOOR_ID, "trap", "rule_floor", "direction"),
    ]
    assert {r.pair_id for r in rows} == {PARENT_ID}
    assert rows[2].claim == "Memory decreased in treated mice."
    assert all(
        (r.problems, r.origin_id, r.kind, r.question_id) == ((), WRITER, KIND, "fx-glp1-q1") for r in rows
    )


def test_generation_is_deterministic() -> None:
    assert _generate(_writer_ports()[0]) == _generate(_writer_ports()[0])


def test_a_writer_failure_is_one_counted_row() -> None:
    rows = parse_draft(_generate(_writer_ports({SOURCE: FailureKind.CONTENT_FILTERED})[0]))
    assert [(r.role, r.claim, r.failure) for r in rows] == [("parent", None, FailureKind.CONTENT_FILTERED)]


def test_a_gated_claim_is_kept_with_its_problems() -> None:
    copied = TrapDraft(
        parent="Mice received the drug. Memory improved. These findings suggest a benefit.", trap=TRAP
    )
    rows = parse_draft(_generate(_writer_ports({SOURCE: copied})[0]))
    assert rows[0].problems  # copies the abstract: excluded from the sheet, not from the draft


def test_the_budget_is_checked_before_any_call() -> None:
    ports, source, writer = _writer_ports()
    with pytest.raises(TrapBudgetError, match="need up to 2 live calls"):
        _generate(ports, budget=1)
    assert (source.calls, writer.calls) == ([], 0)


def test_an_infeasible_target_is_refused_before_any_call() -> None:
    ports, source, writer = _writer_ports()
    with pytest.raises(TrapSamplingError):
        generate(ports, FILES, SPEC, per_kind=1, origin_id=WRITER, max_live_calls=40, kinds=SCORED_KINDS)
    assert (source.calls, writer.calls) == ([], 0)


def test_an_unsealed_dataset_is_refused_before_any_call() -> None:
    ports, source, writer = _writer_ports()
    with pytest.raises(TrapInputError, match="not intact and sealed"):
        _generate(ports, files={k: v for k, v in FILES.items() if k != SEALED})
    assert (source.calls, writer.calls) == ([], 0)


def test_a_source_missing_from_its_dev_pool_is_refused_before_drafting() -> None:
    pools = {q: tuple(p for p in ps if p.source_id != SOURCE) for q, ps in world().items()}
    ports, _, writer = _writer_ports(pools=pools)
    with pytest.raises(TrapPoolError, match=SOURCE):
        _generate(ports)
    assert writer.calls == 0


def test_an_edited_draft_is_refused() -> None:
    draft = _generate(_writer_ports()[0])
    with pytest.raises(TrapInputError, match="canonical"):
        parse_draft(draft.replace(b'"claim":', b'"claim" :', 1))


def test_the_sheet_is_bound_to_its_draft() -> None:
    ports, source, _ = _writer_ports()
    draft = _generate(ports)
    sheet = _decide(sheet_for(source, draft, FILES, SPEC))
    other = draft_bytes(
        parse_draft(_generate(_writer_ports({SOURCE: TrapDraft(parent=PARENT, trap="Other.")})[0]))
    )
    with pytest.raises(TrapAuditError, match="not made from"):
        apply_audit(other, sheet, FILES, SPEC, PACK)


def test_apply_audit_commits_confirmed_rows_with_ground_truth() -> None:
    items = parse_set(_committed_set())
    assert [i.id for i in items] == sorted([PARENT_ID, TRAP_ID, FLOOR_ID])
    by_id = {i.id: i for i in items}
    assert (by_id[PARENT_ID].expected_disposition, by_id[PARENT_ID].expected_label) == (
        Disposition.PASSED,
        Label.SUPPORTED,
    )
    assert (by_id[TRAP_ID].expected_label, by_id[TRAP_ID].expected_reason) == (Label.OVERSTATED, KIND)
    assert (by_id[FLOOR_ID].expected_disposition, by_id[FLOOR_ID].expected_label) == (
        Disposition.FLAGGED,
        None,
    )
    assert all((i.origin, i.confirmed_by) == ("model", "author") for i in items)


def test_a_rejected_parent_drops_its_traps() -> None:
    with pytest.raises(TrapInputError, match="nothing to commit"):
        _committed_set(reject=frozenset({PARENT_ID}))


def test_the_committed_set_holds_no_abstract_text() -> None:
    assert b"Mice received the drug" not in _committed_set()


def _items(data: bytes) -> list[dict[str, object]]:
    return [json.loads(x) for x in data.decode().splitlines()]


def _set_of(rows: Sequence[Mapping[str, object]]) -> bytes:
    return set_bytes(tuple(TrapItem.model_validate(r) for r in rows))


def test_a_committed_set_passes_its_own_checks() -> None:
    assert set_problems(_committed_set(), FILES, SPEC, PACK) == []


def test_a_test_question_is_refused() -> None:
    rows = _items(_committed_set())
    rows[0]["question_id"] = "fx-glp1-q2"
    assert f"{rows[0]['id']}: fx-glp1-q2 is not a dev question" in set_problems(
        _set_of(rows), FILES, SPEC, PACK
    )


def test_a_test_source_is_refused() -> None:
    rows = [  # ids are opaque hashes of the source, so they move with it
        {
            **i.model_dump(mode="json"),
            "source_id": "MED:4",
            "id": opaque_id("MED:4", i.role, i.rule),
            "pair_id": opaque_id("MED:4", "parent", None),
        }
        for i in parse_set(_committed_set())
    ]
    assert any("MED:4 is not a dev source" in p for p in set_problems(_set_of(rows), FILES, SPEC, PACK))


def test_a_changed_abstract_hash_is_refused() -> None:
    rows = _items(_committed_set())
    rows[0]["abstract_sha256"] = "d" * 64
    assert any("differs from the sealed dataset" in p for p in set_problems(_set_of(rows), FILES, SPEC, PACK))


def test_a_trap_without_its_parent_is_refused() -> None:
    rows = [r for r in _items(_committed_set()) if r["role"] == "trap"]
    assert any("is not in the set" in p for p in set_problems(_set_of(rows), FILES, SPEC, PACK))


def test_a_claim_echoing_a_rule_pack_example_is_refused() -> None:
    example = next(e.claim for r in PACK.rules for e in r.examples)
    rows = _items(_committed_set())
    trap = next(r for r in rows if r["id"] == TRAP_ID)
    trap["claim"] = " ".join(example.split()[:30])
    assert any(p.startswith(f"{TRAP_ID}: ") for p in set_problems(_set_of(rows), FILES, SPEC, PACK))


def test_a_non_canonical_set_is_refused() -> None:
    data = _committed_set()
    assert "the set is not canonical" in " ".join(
        set_problems(b"\n".join(reversed(data.splitlines())) + b"\n", FILES, SPEC, PACK)
    )


class RecordingVerifier(BaseVerifier):
    def __init__(self, inner: BaseVerifier) -> None:
        self.inner = inner
        self.claims: list[Claim] = []

    @override
    def verify(self, claim: Claim, paper: Paper, rules: RulePack) -> Verdict | VerifierFailure:
        self.claims.append(claim)
        return self.inner.verify(claim, paper, rules)


def _output(label: Label, reason: OverstatedReason | None = None) -> VerifierOutput:
    return VerifierOutput(
        label=label, overstated_reason=reason, evidence="Memory improved.", reason="Read it."
    )


SCRIPT: Script = {
    (PARENT_ID, SOURCE): _output(Label.SUPPORTED),
    (TRAP_ID, SOURCE): _output(Label.OVERSTATED, KIND),
    (FLOOR_ID, SOURCE): FailureKind.CONTENT_FILTERED,
}


def _verify(
    data: bytes, verifier: BaseVerifier, family: ModelFamily = ModelFamily.OPENAI, budget: int | None = 40
) -> tuple[bytes, QueryLiteratureSource]:
    source = QueryLiteratureSource(world())
    result = verify_set(
        TrapVerifyPorts(literature=source, verifier=verifier, rules=PACK),
        data,
        FILES,
        SPEC,
        judge_sha256="b" * 64,
        verifier="verifier-deployment",
        verifier_family=ModelFamily.ANTHROPIC,
        family_of=lambda _: family,
        max_live_calls=budget,
    )
    return trap_result_bytes(result), source


def _families(deployment: str) -> ModelFamily:
    if deployment == "unknown-writer":
        raise UnknownDeploymentError(deployment, {})
    return ModelFamily.ANTHROPIC if deployment == "verifier-deployment" else ModelFamily.OPENAI


def _result_problems(data: bytes, result: bytes, judge: str = "b" * 64) -> list[str]:
    return result_problems(
        data, result, FILES, judge_sha256=judge, verifier="verifier-deployment", family_of=_families
    )


def test_the_verifier_receives_exactly_the_claim_text() -> None:
    data = _committed_set()
    verifier = RecordingVerifier(ScriptedVerifier(SCRIPT))
    _verify(data, verifier)
    assert [(c.id, c.text, c.cites) for c in verifier.claims] == [
        (i.id, i.claim, (i.source_id,)) for i in parse_set(data)
    ]


def test_verify_counts_every_item_and_a_failure_is_not_caught() -> None:
    data = _committed_set()
    out, source = _verify(data, ScriptedVerifier(SCRIPT))
    result = json.loads(out)
    assert len(source.calls) == 1
    assert result["trap_set_sha256"] == sha256_hex(data)
    assert result["corpus_seal"] == sha256_hex(FILES[MANIFEST])
    assert result["writer_family_flag"] is False
    by = {(r["role"], r["generator"]): r for r in result["counts"]["rows"]}
    assert (
        by["parent", "model"]["passed"],
        by["trap", "model"]["flagged"],
        by["trap", "model"]["exact"],
    ) == (1, 1, 1)
    assert (by["trap", "rule_floor"]["failed"], by["trap", "rule_floor"]["flagged"]) == (1, 0)
    assert _result_problems(data, out) == []


def test_the_same_family_is_flagged() -> None:
    out, _ = _verify(_committed_set(), ScriptedVerifier(SCRIPT), family=ModelFamily.ANTHROPIC)
    assert json.loads(out)["writer_family_flag"] is True


def test_verify_checks_the_budget_before_any_fetch() -> None:
    with pytest.raises(TrapBudgetError):
        _verify(_committed_set(), ScriptedVerifier(SCRIPT), budget=2)


def test_verify_refuses_a_bad_set_before_any_fetch() -> None:
    rows = _items(_committed_set())
    rows[0]["question_id"] = "fx-glp1-q2"
    verifier = RecordingVerifier(ScriptedVerifier(SCRIPT))
    with pytest.raises(TrapInputError, match="not a dev question"):
        _verify(_set_of(rows), verifier)
    assert verifier.claims == []


def test_a_result_with_edited_counts_or_for_another_set_is_refused() -> None:
    data = _committed_set()
    out, _ = _verify(data, ScriptedVerifier(SCRIPT))
    result = json.loads(out)
    flagged = next(r for r in result["counts"]["rows"] if r["role"] == "parent")
    flagged["passed"], flagged["flagged"] = 0, 1
    edited = (json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    assert "the recorded counts do not match the outcomes" in _result_problems(data, edited)
    other = _set_of([r for r in _items(data) if r["generator"] == "model"])
    assert "the result is for another trap set" in _result_problems(other, out)


def test_a_result_with_another_judge_seal_or_family_flag_is_refused() -> None:
    data = _committed_set()
    out, _ = _verify(data, ScriptedVerifier(SCRIPT))
    assert "names another judge or verifier" in " ".join(_result_problems(data, out, judge="e" * 64))
    result = json.loads(out)
    result["corpus_seal"], result["writer_family_flag"] = "f" * 64, True
    edited = (json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    problems = _result_problems(data, edited)
    assert "the result is for another sealed dataset" in problems
    assert "writer_family_flag does not match the writers and the verifier" in problems


def test_an_edited_rule_floor_claim_is_refused() -> None:
    rows = _items(_committed_set())
    floor = next(r for r in rows if r["id"] == FLOOR_ID)
    floor["claim"] = "Memory vanished in treated mice."
    assert f"{FLOOR_ID}: not the direction rule-floor mutation of its parent" in set_problems(
        _set_of(rows), FILES, SPEC, PACK
    )


def test_a_kind_the_source_is_not_a_candidate_for_is_refused() -> None:
    rows = _items(_committed_set())
    for row in rows:
        row["kind"] = OverstatedReason.CORRELATION_AS_CAUSATION.value
        if row["id"] == TRAP_ID:
            row["expected_reason"] = OverstatedReason.CORRELATION_AS_CAUSATION.value
    problems = set_problems(_set_of(rows), FILES, SPEC, PACK)
    assert f"{PARENT_ID}: correlation_as_causation is not a scored sieve candidate of its source" in problems


def test_a_source_ranked_outside_its_questions_pool_is_refused() -> None:
    lines: list[str] = []
    for line in FILES[DEV_SOURCES].decode().splitlines():
        row = json.loads(line)
        if row["source_id"] == SOURCE:
            row["ranks"] = [{**r, "rank": SPEC.pool_hits + 1} for r in row["ranks"]]
        lines.append(json.dumps(row))
    files = {**FILES, DEV_SOURCES: ("\n".join(lines) + "\n").encode()}
    problems = set_problems(_committed_set(), files, SPEC, PACK)
    assert any("is not in the pool of fx-glp1-q1" in p for p in problems)


FLOOR_PARENT = opaque_id(SOURCE, "parent", "direction")


def test_a_rule_floor_parent_is_invalid() -> None:
    row = next(r for r in _items(_committed_set()) if r["id"] == PARENT_ID)
    with pytest.raises(ValidationError, match="drafted by the model"):
        TrapItem.model_validate(
            {
                **row,
                "id": FLOOR_PARENT,
                "pair_id": FLOOR_PARENT,
                "generator": "rule_floor",
                "rule": "direction",
            }
        )


def test_an_unknown_writer_is_refused_before_any_fetch() -> None:
    rows = [{**r, "origin_id": "unknown-writer"} for r in _items(_committed_set())]
    verifier = RecordingVerifier(ScriptedVerifier(SCRIPT))
    source = QueryLiteratureSource(world())
    with pytest.raises(TrapInputError, match="not in the model catalog"):
        verify_set(
            TrapVerifyPorts(literature=source, verifier=verifier, rules=PACK),
            _set_of(rows),
            FILES,
            SPEC,
            judge_sha256="b" * 64,
            verifier="verifier-deployment",
            verifier_family=ModelFamily.ANTHROPIC,
            family_of=_families,
            max_live_calls=40,
        )
    assert (source.calls, verifier.claims) == ([], [])
