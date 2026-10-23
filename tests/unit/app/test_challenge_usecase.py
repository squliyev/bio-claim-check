"""`run_challenge` and the offline attestation (I72): sealed dev pairs only, every item judged once."""

import json
from collections.abc import Mapping

import pytest
from tests.support.corpus import SPEC_FILE, QueryLiteratureSource, dataset_files, world

from bio_claim_check.app.container import default_rulepack, load_corpus_spec
from bio_claim_check.app.usecases.challenge import (
    ChallengeInputError,
    ChallengePoolError,
    ChallengePorts,
    ChallengeResult,
    attestation_problems,
    item_problems,
    parse_items,
    result_bytes,
    run_challenge,
)
from bio_claim_check.features.contracts.corpus import SourceEntry
from bio_claim_check.features.contracts.labels import Disposition, FailureKind, Label
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.verdict import VerifierOutput
from bio_claim_check.features.corpus.layout import DEV_SOURCES, MANIFEST, SEALED
from bio_claim_check.features.corpus.seal import sealed_bytes
from bio_claim_check.features.corpus.serialise import sha256_hex
from bio_claim_check.features.verify.scripted_verifier import Script, ScriptedVerifier

pytestmark = pytest.mark.unit
SPEC = load_corpus_spec(SPEC_FILE)
JUDGE = "b" * 64
VERIFIER = "claude-opus-4-8"


def _sealed() -> dict[str, bytes]:
    files = dataset_files()
    return {**files, SEALED: sealed_bytes(files[MANIFEST])}


FILES = _sealed()
SHAS = {
    e.source_id: e.abstract_sha256
    for e in (SourceEntry.model_validate_json(x) for x in FILES[DEV_SOURCES].decode().splitlines())
}


def _row(cid: str, source: str, expected: str, **over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": cid,
        "question_id": "fx-glp1-q1",
        "source_id": source,
        "abstract_sha256": SHAS.get(source, "c" * 64),
        "claim": "The drug improved memory in mice.",
        "expected": expected,
        "expected_reason": None,
        "label_source": "ai_draft_author_confirmed",
    }
    return {**row, **over}


def _jsonl(*rows: dict[str, object]) -> bytes:
    return "".join(json.dumps(r) + "\n" for r in rows).encode()


SET = _jsonl(_row("ch2", "MED:5", "not_in_source"), _row("ch1", "MED:11", "supported"))
SCRIPT: Script = {
    ("ch1", "MED:11"): VerifierOutput(
        label=Label.SUPPORTED, overstated_reason=None, evidence="Memory improved.", reason="Stated."
    ),
    ("ch2", "MED:5"): VerifierOutput(
        label=Label.NOT_IN_SOURCE, overstated_reason=None, evidence=None, reason="Not mentioned."
    ),
}


def _ports(
    script: Script = SCRIPT, pools: Mapping[str, tuple[Paper, ...]] | None = None
) -> tuple[ChallengePorts, QueryLiteratureSource]:
    source = QueryLiteratureSource(world() if pools is None else pools)
    return ChallengePorts(
        literature=source, verifier=ScriptedVerifier(script), rules=default_rulepack()
    ), source


def _run(
    data: bytes = SET, script: Script = SCRIPT, pools: Mapping[str, tuple[Paper, ...]] | None = None
) -> bytes:
    ports, _ = _ports(script, pools)
    result = run_challenge(ports, data, FILES, SPEC, judge_sha256=JUDGE, verifier=VERIFIER)
    return result_bytes(result)


def test_judges_each_item_once_from_its_dev_pool_sorted_by_id() -> None:
    ports, source = _ports()
    result = run_challenge(ports, SET, FILES, SPEC, judge_sha256=JUDGE, verifier=VERIFIER)
    assert len(source.calls) == 1  # one dev question, one search
    assert [o.id for o in result.outcomes] == ["ch1", "ch2"]
    assert [o.disposition for o in result.outcomes] == [Disposition.PASSED, Disposition.FLAGGED]
    assert (result.challenge_sha256, result.score.agree, result.score.passed) == (sha256_hex(SET), 2, True)
    assert _run() == result_bytes(result)  # same inputs, same bytes


def test_a_verifier_failure_is_an_outcome_not_a_gap() -> None:
    result = json.loads(_run(script={**SCRIPT, ("ch2", "MED:5"): FailureKind.CONTENT_FILTERED}))
    failed = result["outcomes"][1]
    assert (failed["disposition"], failed["failure_kind"], failed["label"]) == (
        "failed",
        "content_filtered",
        None,
    )


@pytest.mark.parametrize(
    ("row", "problem"),
    [
        (_row("ch1", "MED:11", "supported", question_id="fx-glp1-q2"), "not a dev question"),
        (_row("ch1", "MED:1", "supported"), "not a dev source"),
        (_row("ch1", "MED:11", "supported", abstract_sha256="d" * 64), "differs from the sealed"),
    ],
)
def test_items_must_be_sealed_dev_pairs_before_any_fetch(row: dict[str, object], problem: str) -> None:
    ports, source = _ports()
    with pytest.raises(ChallengeInputError, match=problem):
        run_challenge(ports, _jsonl(row), FILES, SPEC, judge_sha256=JUDGE, verifier=VERIFIER)
    assert source.calls == []


def test_a_source_outside_its_question_pool_is_refused() -> None:
    files = {**FILES}
    rows = [json.loads(x) for x in files[DEV_SOURCES].decode().splitlines()]
    assert rows[0]["source_id"] == "MED:5"
    rows[0]["ranks"] = [{"question_id": "fx-glp1-q2", "rank": 1}]
    files[DEV_SOURCES] = "".join(json.dumps(r) + "\n" for r in rows).encode()
    assert item_problems(parse_items(SET), files) == ["ch2: MED:5 is not in the pool of fx-glp1-q1"]


def test_an_unsealed_dataset_is_refused() -> None:
    ports, source = _ports()
    files = {k: v for k, v in FILES.items() if k != SEALED}
    with pytest.raises(ChallengeInputError, match="not intact and sealed"):
        run_challenge(ports, SET, files, SPEC, judge_sha256=JUDGE, verifier=VERIFIER)
    assert source.calls == []


def test_a_source_missing_from_the_live_pool_stops_the_run() -> None:
    pools = {q: tuple(p for p in ps if p.source_id != "MED:11") for q, ps in world().items()}
    with pytest.raises(ChallengePoolError, match="ch1"):
        _run(pools=pools)


@pytest.mark.parametrize(
    ("data", "problem"),
    [
        (b"\xff", "not UTF-8"),
        (b"", "empty"),
        (b"{}\n", "line 1"),
        (_jsonl(_row("ch1", "MED:11", "supported"), _row("ch1", "MED:5", "supported")), "duplicate id"),
        (
            _jsonl(_row("ch1", "MED:11", "supported"), _row("ch2", "MED:11", "supported")),
            "duplicate source_id",
        ),
    ],
)
def test_malformed_challenge_files_are_refused(data: bytes, problem: str) -> None:
    with pytest.raises(ChallengeInputError, match=problem):
        parse_items(data)


def test_a_consistent_record_attests() -> None:
    assert attestation_problems(SET, _run(), FILES, judge_sha256=JUDGE, verifier=VERIFIER) == []


def test_attestation_names_each_mismatch() -> None:
    result = _run()
    other_set = _jsonl(_row("ch1", "MED:11", "supported"), _row("ch2", "MED:5", "not_in_source"))
    problems = attestation_problems(other_set, result, FILES, judge_sha256="e" * 64, verifier="gpt-6.1-sol")
    assert problems == [
        "the result is for another challenge set",
        "the result was made by another judge (prompt, rules, code or model changed)",
        "the result names verifier claude-opus-4-8, the code uses gpt-6.1-sol",
    ]
    assert attestation_problems(SET, result + b"\n", FILES, judge_sha256=JUDGE, verifier=VERIFIER) == [
        "the result is not in canonical form"
    ]


def test_attestation_recomputes_the_score() -> None:
    doc = json.loads(_run())
    doc["score"]["near"] = 1  # reported, not gated: `passed` still reads back
    edited = json.dumps(doc).encode()
    assert "the recorded score does not match its outcomes" in attestation_problems(
        SET, edited, FILES, judge_sha256=JUDGE, verifier=VERIFIER
    )
    doc = json.loads(_run(script={**SCRIPT, ("ch2", "MED:5"): SCRIPT[("ch1", "MED:11")]}))
    assert doc["score"]["unsafe_passes"] == 0  # the quote is not in MED:5, so it is not passed
    bad: dict[str, object] = json.loads(
        _run(script={**SCRIPT, ("ch1", "MED:11"): FailureKind.PROVIDER_ERROR})
    )
    assert (
        ChallengeResult.model_validate(bad).score.passed is False
    )  # one failure in two items breaks the 1/8 cap
    assert attestation_problems(SET, result_bytes_of(bad), FILES, judge_sha256=JUDGE, verifier=VERIFIER) == [
        "the challenge rule is not met"
    ]


def test_attestation_reports_unreadable_inputs_and_mismatched_ids() -> None:
    assert attestation_problems(b"", _run(), FILES, judge_sha256=JUDGE, verifier=VERIFIER) == [
        "the challenge file is empty"
    ]
    assert attestation_problems(SET, b"{}", FILES, judge_sha256=JUDGE, verifier=VERIFIER)[0].startswith(
        "the result is not valid"
    )
    one = _jsonl(_row("ch1", "MED:11", "supported"))
    problems = attestation_problems(one, _run(), FILES, judge_sha256=JUDGE, verifier=VERIFIER)
    assert problems[-1] == "items and outcomes must be non-empty and hold the same unique ids"


def result_bytes_of(doc: dict[str, object]) -> bytes:
    return result_bytes(ChallengeResult.model_validate(doc))
