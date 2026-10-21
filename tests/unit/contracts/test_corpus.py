"""Corpus contracts (ADR 0010): the spec rejects inconsistent input, and dataset rows check themselves."""

from typing import Any

import pytest
from pydantic import ValidationError

from bio_claim_check.features.contracts.corpus import (
    NLM_NOTICE,
    TRAP_KINDS,
    AuditDecision,
    AuditRecord,
    CorpusManifest,
    CorpusSpec,
    CorpusSpecError,
    CorpusSplit,
    NeverReason,
    QuestionEntry,
    SourceEntry,
    parse_corpus_spec,
)
from bio_claim_check.features.contracts.labels import OverstatedReason

SHA = "0" * 64


def spec_data() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "sieve_version": 2,
        "pool_hits": 100,
        "cutoff": "2024-12-31",
        "split_salt": "bio-claim-check/split/v1",
        "audit_salt": "bio-claim-check/audit/v1",
        "dev_fraction": 0.5,
        "audit_n": 50,
        "trap_kinds": [k.value for k in TRAP_KINDS],
        "domains": [
            {"id": "glp1-neuro", "held_out": False, "description": "GLP-1 RAs in AD and PD"},
            {"id": "statin-neuro", "held_out": True, "description": "Statins in dementia"},
        ],
        "questions": [
            {
                "id": "glp1-q1",
                "domain": "glp1-neuro",
                "split": "dev",
                "text": "Does exenatide slow PD?",
                "search": "exenatide AND parkinson",
                "answerable": True,
            },
            {
                "id": "statin-q1",
                "domain": "statin-neuro",
                "split": "test",
                "text": "Do statins prevent dementia?",
                "search": "statin AND dementia",
                "answerable": False,
            },
        ],
    }


def problems_of(data: object) -> str:
    with pytest.raises(CorpusSpecError) as err:
        parse_corpus_spec(data, "corpus.yaml")
    return "\n".join(err.value.problems)


def test_valid_spec_parses() -> None:
    spec = parse_corpus_spec(spec_data(), "corpus.yaml")
    assert isinstance(spec, CorpusSpec)
    assert spec.held_out_domain() == "statin-neuro"
    assert spec.questions[0].split is CorpusSplit.DEV


def test_empty_file_is_named() -> None:
    assert problems_of(None) == "corpus.yaml: the file is empty"


def test_root_problem_has_a_location() -> None:
    assert problems_of([1]).startswith("corpus.yaml: (root): ")


def test_field_problem_names_its_path() -> None:
    data = spec_data()
    del data["questions"][0]["search"]
    assert "corpus.yaml: questions.0.search: Field required" in problems_of(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", True),
        ("schema_version", 1.0),
        ("schema_version", 2),
        ("sieve_version", True),
        ("pool_hits", 50),
        ("cutoff", 1735603200),
        ("cutoff", "31/12/2024"),
        ("dev_fraction", 1),
        ("dev_fraction", 0.0),
        ("dev_fraction", 1.0),
        ("audit_n", 0),
        ("audit_n", 50.0),
        ("trap_kinds", []),
        ("split_salt", "  "),
    ],
)
def test_bad_scalar_is_rejected(field: str, value: object) -> None:
    data = spec_data()
    data[field] = value
    assert f"corpus.yaml: {field}" in problems_of(data)


def test_a_date_object_is_accepted() -> None:
    from datetime import date

    data = spec_data()
    data["cutoff"] = date(2024, 12, 31)
    assert parse_corpus_spec(data, "x").cutoff == date(2024, 12, 31)


def mutate(change: str) -> dict[str, Any]:
    data = spec_data()
    domains, questions = data["domains"], data["questions"]
    match change:
        case "duplicate_domain":
            domains[1]["id"] = "glp1-neuro"
            questions[1]["domain"] = "glp1-neuro"
        case "no_held_out":
            domains[1]["held_out"] = False
        case "two_held_out":
            domains[0]["held_out"] = True
            questions[0]["split"] = "test"
        case "duplicate_question":
            questions[1]["id"] = "glp1-q1"
        case "unknown_domain":
            questions[0]["domain"] = "nowhere"
        case "held_out_in_dev":
            questions[1]["split"] = "dev"
        case "duplicate_kind":
            data["trap_kinds"] = [TRAP_KINDS[0].value, TRAP_KINDS[0].value]
        case "unsupported_kind":
            data["trap_kinds"] = [OverstatedReason.SURROGATE_AS_CLINICAL.value, OverstatedReason.OTHER.value]
        case _:  # pragma: no cover - a typo in the parametrize list
            raise AssertionError(change)
    return data


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("duplicate_domain", "domain ids must be unique"),
        ("no_held_out", "exactly one domain must be held out"),
        ("two_held_out", "exactly one domain must be held out"),
        ("duplicate_question", "question ids must be unique"),
        ("unknown_domain", "question glp1-q1: unknown domain 'nowhere'"),
        ("held_out_in_dev", "question statin-q1: a held-out domain's questions must be in test"),
        ("duplicate_kind", "trap_kinds must be unique"),
        ("unsupported_kind", "trap_kinds not supported by sieve v2: surrogate_as_clinical, other"),
    ],
)
def test_inconsistent_spec_is_rejected(change: str, message: str) -> None:
    assert message in problems_of(mutate(change))


def test_unknown_key_is_rejected() -> None:
    data = spec_data()
    data["questions"][0]["hint"] = "x"
    assert "questions.0.hint: Extra inputs are not permitted" in problems_of(data)


def entry(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "source_id": "MED:2",
        "year": 2020,
        "ranks": [{"question_id": "a-q1", "rank": 3}, {"question_id": "b-q1", "rank": 1}],
        "cluster_id": "MED:2",
        "split": "dev",
        "retracted": False,
        "publication_types": ["Journal Article"],
        "mesh_headings": ["Animals"],
        "abstract_sha256": SHA,
        "never_because": [],
        "candidates": [
            {"kind": "preclinical_to_clinical", "rule": "animals_not_humans", "mesh": ["Animals"]}
        ],
    }
    data.update(overrides)
    return data


def test_valid_source_entry() -> None:
    assert SourceEntry.model_validate(entry()).candidates[0].rule == "animals_not_humans"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ranks": []}, "at least 1 item"),
        (
            {"ranks": [{"question_id": "b-q1", "rank": 1}, {"question_id": "a-q1", "rank": 3}]},
            "ranks must be sorted by question id, one per question",
        ),
        (
            {"ranks": [{"question_id": "a-q1", "rank": 1}, {"question_id": "a-q1", "rank": 3}]},
            "ranks must be sorted by question id, one per question",
        ),
        ({"retracted": True}, "never_because must be ['retracted']"),
        ({"never_because": ["review"]}, "never_because must be []"),
        (
            {"candidates": [{"kind": "preclinical_to_clinical", "rule": "in_vitro"}] * 2},
            "at most one candidate per kind",
        ),
        (
            {"retracted": True, "never_because": ["retracted"]},
            "an excluded source has no candidates",
        ),
        (
            {"mesh_headings": None, "never_because": ["mesh_not_indexed"]},
            "a source without MeSH cannot be a candidate for a MeSH kind",
        ),
        ({"abstract_sha256": "A" * 64}, "abstract_sha256"),
    ],
)
def test_inconsistent_source_entry_is_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError) as err:
        SourceEntry.model_validate(entry(**overrides))
    assert message in str(err.value)


def test_unindexed_source_may_be_a_text_kind_candidate() -> None:
    row = entry(
        mesh_headings=None,
        never_because=["mesh_not_indexed"],
        candidates=[
            {"kind": "nonsignificant_as_effect", "rule": "null_result", "span": {"start": 0, "end": 4}}
        ],
    )
    assert SourceEntry.model_validate(row).never_because == (NeverReason.MESH_NOT_INDEXED,)


def test_review_and_unknown_types_are_derived() -> None:
    row = entry(publication_types=["Review"], never_because=["review"], candidates=[])
    assert SourceEntry.model_validate(row).never_because == (NeverReason.REVIEW,)
    row = entry(publication_types=[], never_because=["unknown_publication_types"], candidates=[])
    assert SourceEntry.model_validate(row).never_because == (NeverReason.UNKNOWN_PUBLICATION_TYPES,)


def question_entry(pool_size: int, split_pool_size: int) -> dict[str, Any]:
    question = spec_data()["questions"][0]
    return {
        **question,
        "query": "(exenatide) AND FIRST_PDATE",
        "response_sha256": SHA,
        "pool_size": pool_size,
        "split_pool_size": split_pool_size,
        "pool_sha256": SHA,
    }


def test_split_pool_may_equal_the_pool() -> None:
    assert QuestionEntry.model_validate(question_entry(3, 3)).split_pool_size == 3


def test_split_pool_cannot_exceed_the_pool() -> None:
    with pytest.raises(ValidationError, match="split_pool_size cannot exceed pool_size"):
        QuestionEntry.model_validate(question_entry(2, 3))


def manifest(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": 1,
        "tool_version": "0.1.0",
        "declared_fetched_on": "2026-10-21",
        "spec_sha256": SHA,
        "spec_file_sha256": SHA,
        "notice": NLM_NOTICE,
        "files": [{"name": "dev/sources.jsonl", "sha256": SHA}, {"name": "questions.jsonl", "sha256": SHA}],
        "candidate_counts": [{"domain": "glp1-neuro", "split": "dev", "kind": "certainty_inflation", "n": 0}],
    }
    data.update(overrides)
    return data


def test_valid_manifest() -> None:
    assert CorpusManifest.model_validate(manifest()).notice == NLM_NOTICE


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"notice": "Data from PubMed."}, "notice must be the NLM credit"),
        (
            {
                "files": [
                    {"name": "questions.jsonl", "sha256": SHA},
                    {"name": "dev/sources.jsonl", "sha256": SHA},
                ]
            },
            "files must be sorted by name, each once",
        ),
        (
            {"files": [{"name": "a", "sha256": SHA}, {"name": "a", "sha256": SHA}]},
            "files must be sorted by name, each once",
        ),
        ({"declared_fetched_on": 20261021}, "YYYY-MM-DD"),
    ],
)
def test_inconsistent_manifest_is_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError) as err:
        CorpusManifest.model_validate(manifest(**overrides))
    assert message in str(err.value)


def decision(source_id: str = "MED:1", verdict: str = "confirm", reason: str | None = None) -> dict[str, Any]:
    return {"source_id": source_id, "decision": verdict, "reason": reason}


def test_a_confirm_has_no_reason_and_a_reject_needs_one() -> None:
    assert AuditDecision.model_validate(decision()).reason is None
    assert AuditDecision.model_validate(decision(verdict="reject", reason="human cells")).reason
    for bad in (decision(verdict="reject"), decision(reason="why"), decision(verdict="reject", reason=" ")):
        with pytest.raises(ValidationError):
            AuditDecision.model_validate(bad)
    with pytest.raises(ValidationError):
        AuditDecision.model_validate(decision(verdict="maybe"))


def record(**overrides: Any) -> dict[str, Any]:
    return {
        "split": "dev",
        "kind": "preclinical_to_clinical",
        "corpus_seal": SHA,
        "prompts_sha256": SHA,
        "decisions": [decision("MED:1"), decision("MED:2", "reject", "cells are human")],
    } | overrides


def test_valid_audit_record() -> None:
    assert len(AuditRecord.model_validate(record()).decisions) == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"decisions": []},
        {"decisions": [decision("MED:1"), decision("MED:1")]},
        {"corpus_seal": "abc"},
        {"prompts_sha256": "G" * 64},
        {"split": "train"},
        {"extra": 1},
    ],
)
def test_inconsistent_audit_record_is_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AuditRecord.model_validate(record(**overrides))
