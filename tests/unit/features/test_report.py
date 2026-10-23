"""Report integrity: stored inputs, derived numbers (I19, I20)."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from bio_claim_check.common.model_family import ModelFamily
from bio_claim_check.features.contracts.answer import Answer
from bio_claim_check.features.contracts.finding import Finding, FindingKind
from bio_claim_check.features.contracts.labels import AnswerMode, Disposition, FailureKind, Label
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.verdict import (
    CitationNotRetrieved,
    Claim,
    PairOutcome,
    Verdict,
    VerifierFailure,
    VerifierOutput,
)
from bio_claim_check.features.report.build import build_report
from bio_claim_check.features.report.models import FAKE_NOTICE, LIVE_NOTICE, ModelUse, Report, RunModels

pytestmark = pytest.mark.unit

P1 = Paper(source_id="FAKE:1", title="One", year=2020, raw_abstract="<p>X reduced plaque in mice.</p>")
P2 = Paper(source_id="FAKE:2", title="Two", year=None, raw_abstract="Y raised plaque in rats.")
C1 = Claim(id="c1", text="X reduces plaque.", cites=("FAKE:1", "FAKE:9"))
C2 = Claim(id="c2", text="Y raises plaque.", cites=("FAKE:2",))
C3 = Claim(id="c3", text="X reduces plaque too.", cites=("FAKE:1",))


def _verdict(claim_id: str, paper: Paper, quote: str) -> Verdict:
    out = VerifierOutput(label=Label.SUPPORTED, overstated_reason=None, evidence=quote, reason="r")
    return Verdict.finalise(claim_id, paper.source_id, out, paper.abstract)


def _outcomes() -> dict[str, dict[str, PairOutcome]]:
    return {
        "c1": {
            "FAKE:1": _verdict("c1", P1, "X reduced plaque"),
            "FAKE:9": CitationNotRetrieved(claim_id="c1", source_id="FAKE:9"),
        },
        "c2": {"FAKE:2": VerifierFailure(claim_id="c2", source_id="FAKE:2", kind=FailureKind.PROVIDER_ERROR)},
        "c3": {"FAKE:1": _verdict("c3", P1, "X reduced plaque in mice")},
    }


FINDINGS = (
    Finding(kind=FindingKind.INVENTED_CITATION, claim_id="c1", source_id="FAKE:9", detail="not retrieved"),
)


def _report() -> Report:
    answer = Answer(question="Does X work?", mode=AnswerMode.OVER_EAGER, claims=(C1, C2, C3))
    return build_report(
        provenance="fake",
        models=None,
        answer=answer,
        papers=(P1, P2),
        findings=FINDINGS,
        outcomes=_outcomes(),
    )


def _dump() -> dict[str, Any]:
    return _report().model_dump(mode="json")


def test_counts_are_derived_over_pairs_and_claims() -> None:
    report = _report()
    pairs = {
        Disposition.PASSED: 2,
        Disposition.NEEDS_REVIEW: 0,
        Disposition.FAILED: 1,
        Disposition.FLAGGED: 1,
    }
    claims = {
        Disposition.PASSED: 1,
        Disposition.NEEDS_REVIEW: 0,
        Disposition.FAILED: 1,
        Disposition.FLAGGED: 1,
    }
    assert (report.pair_counts, report.claim_counts) == (pairs, claims)
    assert sum(report.pair_counts.values()) == sum(len(c.claim.cites) for c in report.claims)
    assert sum(report.claim_counts.values()) == len(report.claims)


def test_two_claims_citing_one_source_are_two_pairs() -> None:
    pairs = [(p.result.claim_id, p.result.source_id) for c in _report().claims for p in c.pairs]
    assert pairs.count(("c1", "FAKE:1")) == pairs.count(("c3", "FAKE:1")) == 1


def test_fake_report_carries_its_notice() -> None:
    assert _dump()["notice"] == FAKE_NOTICE


GPT = ModelUse(deployment="gpt-x", family=ModelFamily.OPENAI)
CLAUDE = ModelUse(deployment="claude-x", family=ModelFamily.ANTHROPIC)


def _live(models: RunModels | None) -> Report:
    answer = Answer(question="q", mode=AnswerMode.STRICT, claims=())
    return build_report(provenance="live", models=models, answer=answer, papers=(), findings=(), outcomes={})


def test_live_report_names_its_models_and_says_labels_are_model_judgements() -> None:
    dumped = _live(RunModels(answerer=GPT, verifier=CLAUDE)).model_dump(mode="json")
    assert dumped["notice"] == LIVE_NOTICE
    assert "FAKE" not in LIVE_NOTICE
    assert "not expert review" in LIVE_NOTICE
    assert dumped["models"] == {
        "answerer": {"deployment": "gpt-x", "family": "openai"},
        "verifier": {"deployment": "claude-x", "family": "anthropic"},
        "same_family": False,
    }


def test_same_family_is_flagged() -> None:
    assert RunModels(
        answerer=GPT, verifier=ModelUse(deployment="gpt-y", family=ModelFamily.OPENAI)
    ).same_family


def test_models_are_required_for_live_and_absent_for_fake() -> None:
    with pytest.raises(ValidationError, match="models"):
        _live(None)
    dumped = _dump() | {"models": RunModels(answerer=GPT, verifier=CLAUDE).model_dump(mode="json")}
    with pytest.raises(ValidationError, match="models"):
        Report.model_validate(dumped)


def test_a_forged_same_family_is_rejected() -> None:
    forged = RunModels(answerer=GPT, verifier=CLAUDE).model_dump(mode="json") | {"same_family": True}
    with pytest.raises(ValidationError, match="same_family"):
        RunModels.model_validate(forged)


def test_a_stored_family_outside_the_vocabulary_is_rejected() -> None:
    stored = RunModels(answerer=GPT, verifier=CLAUDE).model_dump(mode="json")
    stored["verifier"]["family"] = "fabricated"
    with pytest.raises(ValidationError, match="family"):
        RunModels.model_validate(stored)


def test_an_abstaining_answer_counts_nothing() -> None:
    answer = Answer(question="q", mode=AnswerMode.STRICT, claims=())
    report = build_report(provenance="fake", models=None, answer=answer, papers=(), findings=(), outcomes={})
    assert set(report.pair_counts.values()) == set(report.claim_counts.values()) == {0}


def test_json_round_trip_keeps_outcome_types() -> None:
    again = Report.model_validate_json(_report().model_dump_json())
    assert again == _report()
    assert [type(p.result) for c in again.claims for p in c.pairs] == [
        Verdict,
        CitationNotRetrieved,
        VerifierFailure,
        Verdict,
    ]


@pytest.mark.parametrize(
    "path",
    [
        ("pair_counts", "flagged"),
        ("claim_counts", "passed"),
        ("claims", 0, "disposition"),
        ("claims", 1, "pairs", 0, "disposition"),
        ("notice",),
    ],
    ids=str,
)
def test_a_forged_derived_value_is_rejected(path: tuple[str | int, ...]) -> None:
    dumped = _dump()
    node: Any = dumped
    for key in path[:-1]:
        node = node[key]
    forged: dict[str, object] = {"pair_counts": 99, "claim_counts": 99, "notice": "A RESULT"}
    node[path[-1]] = forged.get(str(path[-1]), "passed")
    with pytest.raises(ValidationError, match="does not match the value derived"):
        Report.model_validate(dumped)


def test_a_dump_without_derived_values_still_loads() -> None:
    dumped = _dump()
    for key in DERIVED:
        del dumped[key]
    assert Report.model_validate(dumped) == _report()


DERIVED = ("notice", "pair_counts", "claim_counts")


def _mutated(**changes: Any) -> dict[str, Any]:
    """A dump with changed inputs; top-level derived values are dropped so the input check is what fires."""
    dumped = {k: v for k, v in _dump().items() if k not in DERIVED}
    return json.loads(json.dumps(dumped | changes))


def test_rejects_duplicate_papers() -> None:
    with pytest.raises(ValidationError, match="source ids must be unique"):
        Report.model_validate(_mutated(papers=[P1.model_dump(), P1.model_dump(), P2.model_dump()]))


def test_rejects_duplicate_claims() -> None:
    dumped = _dump()
    with pytest.raises(ValidationError, match="claim ids must be unique"):
        Report.model_validate(_mutated(claims=[*dumped["claims"], dumped["claims"][1]]))


def test_rejects_a_verdict_for_a_paper_that_was_not_retrieved() -> None:
    with pytest.raises(ValidationError, match="was not retrieved"):
        Report.model_validate(_mutated(papers=[P2.model_dump()]))


def test_rejects_not_retrieved_for_a_retrieved_paper() -> None:
    p9 = Paper(source_id="FAKE:9", title="Nine", year=None, raw_abstract="z")
    with pytest.raises(ValidationError, match="reported as not retrieved"):
        Report.model_validate(_mutated(papers=[P1.model_dump(), P2.model_dump(), p9.model_dump()]))


def test_rejects_a_verdict_whose_span_does_not_relocate() -> None:
    other = Paper(
        source_id="FAKE:1", title="One", year=2020, raw_abstract="Plaque: X reduced plaque in mice."
    )
    with pytest.raises(ValidationError, match="does not match the abstract"):
        Report.model_validate(_mutated(papers=[other.model_dump(), P2.model_dump()]))


def test_rejects_findings_that_do_not_match_not_retrieved_pairs() -> None:
    with pytest.raises(ValidationError, match="findings"):
        Report.model_validate(_mutated(findings=[]))


def test_fake_report_may_not_cite_real_sources() -> None:
    real = Paper(source_id="MED:12345678", title="Real", year=2020, raw_abstract="Y raised plaque in rats.")
    outcomes = _outcomes() | {
        "c2": {
            "MED:12345678": VerifierFailure(
                claim_id="c2", source_id="MED:12345678", kind=FailureKind.PROVIDER_ERROR
            )
        }
    }
    c2 = Claim(id="c2", text="Y raises plaque.", cites=("MED:12345678",))
    answer = Answer(question="q", mode=AnswerMode.STRICT, claims=(C1, c2, C3))
    with pytest.raises(ValidationError, match="only FAKE: sources"):
        build_report(
            provenance="fake",
            models=None,
            answer=answer,
            papers=(P1, real),
            findings=FINDINGS,
            outcomes=outcomes,
        )


def test_pairs_must_follow_citation_order() -> None:
    dumped = _dump()
    dumped["claims"][0]["pairs"].reverse()
    with pytest.raises(ValidationError, match="in order"):
        Report.model_validate(dumped)


def test_pairs_must_belong_to_their_claim() -> None:
    dumped = _dump()
    dumped["claims"][2]["pairs"] = dumped["claims"][0]["pairs"][:1]
    with pytest.raises(ValidationError, match="belongs to"):
        Report.model_validate(dumped)


def test_build_rejects_missing_or_extra_outcomes() -> None:
    answer = Answer(question="q", mode=AnswerMode.STRICT, claims=(C1, C2, C3))
    missing = _outcomes()
    del missing["c1"]["FAKE:9"]
    with pytest.raises(ValueError, match="exactly its cited sources"):
        build_report(
            provenance="fake",
            models=None,
            answer=answer,
            papers=(P1, P2),
            findings=FINDINGS,
            outcomes=missing,
        )
    with pytest.raises(ValueError, match="claims not in the answer"):
        build_report(
            provenance="fake",
            models=None,
            answer=answer,
            papers=(P1, P2),
            findings=FINDINGS,
            outcomes=_outcomes() | {"zz": {}},
        )


def test_rejects_a_finding_about_an_unknown_claim() -> None:
    stray = Finding(kind=FindingKind.INVENTED_CITATION, claim_id="c9", source_id="FAKE:9", detail="x")
    with pytest.raises(ValidationError, match="findings: name claims that are not in the report"):
        Report.model_validate(_mutated(findings=[stray.model_dump(mode="json")]))
