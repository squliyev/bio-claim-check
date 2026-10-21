"""Characterisation: the exact CLI output of `rulepack validate` and `run --fake` (pinned before S05b).

S05b moves YAML parsing, file reading and report publishing between rings. These tests pin every
byte the user sees, so that refactor cannot change a message, an exit code or a run id. The run ids
changed once, deliberately, in S06: `Paper` gained seven defaulted fields (goldens diffed key by key).
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from bio_claim_check.app.cli import app

pytestmark = pytest.mark.unit
runner = CliRunner()

HEADER = "Invalid rule pack ({n} problem(s)):\n"


@pytest.mark.parametrize(
    ("data", "lines"),
    [
        pytest.param(b"a: 1\na: 2\n", ["{p}:2: duplicate key 'a'"], id="duplicate"),
        pytest.param(
            b"a: &x 1\nb: *x\n",
            ["{p}:1: anchors and aliases are not allowed", "{p}:2: anchors and aliases are not allowed"],
            id="anchor-alias",
        ),
        pytest.param(b"# c\n", ["{p}: the file is empty"], id="empty"),
        pytest.param(
            b"base: {a: 1}\nm:\n  <<: {a: 1}\n", ["{p}:3: merge keys (<<) are not allowed"], id="merge"
        ),
        pytest.param(b"a: [1\n", ["{p}:2: expected ',' or ']', but got '<stream end>'"], id="syntax"),
        pytest.param(
            b"a: !!binary aGVsbG8=\nb:\n  - 2024-01-01\n",
            ["{p}: a: bytes values are not allowed", "{p}: b.0: date values are not allowed"],
            id="non-scalar",
        ),
        pytest.param(
            b"schema_version: true\nversion: 1.0\n",
            [
                "{p}: schema_version: Value error, must be the integer 1",
                "{p}: version: Input should be a valid string",
                "{p}: authors: Field required",
                "{p}: rules: Field required",
            ],
            id="model",
        ),
        pytest.param(("a: " + "[" * 2000 + "]" * 2000).encode(), ["{p}: nesting is too deep"], id="deep"),
        pytest.param(
            b"\xff\xfe\xfa",
            ["{p}: cannot read: 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte"],
            id="undecodable",
        ),
    ],
)
def test_validate_errors_are_byte_exact(tmp_path: Path, data: bytes, lines: list[str]) -> None:
    path = tmp_path / "pack.yaml"
    path.write_bytes(data)
    result = runner.invoke(app, ["rulepack", "validate", str(path)])
    assert result.exit_code == 2
    assert result.stdout == ""
    body = "".join(f"  - {line.format(p=path)}\n" for line in lines)
    assert result.stderr == HEADER.format(n=len(lines)) + body


def test_validate_missing_file_is_byte_exact(tmp_path: Path) -> None:
    path = tmp_path / "missing.yaml"
    result = runner.invoke(app, ["rulepack", "validate", str(path)])
    assert result.exit_code == 2
    assert result.stderr == HEADER.format(n=1) + (
        f"  - {path}: cannot read: [Errno 2] No such file or directory: '{path}'\n"
    )


def test_validate_default_pack_is_byte_exact() -> None:
    result = runner.invoke(app, ["rulepack", "validate"])
    assert result.exit_code == 0
    reasons = [
        "preclinical_to_clinical",
        "background_as_result",
        "surrogate_as_clinical",
        "correlation_as_causation",
        "selective_analysis_as_main",
        "nonsignificant_as_effect",
        "dose_or_exposure_extrapolation",
        "population_extrapolation",
        "certainty_inflation",
    ]
    assert result.stdout == (
        "rule pack 0.1.0 (schema 1) by Samir Guliyev\nrules: 9\n"
        + "".join(f"  - {r} ({r}): 2 example(s)\n" for r in reasons)
        + "examples: 18 (18 author-written, 0 reviewed)\n"
    )


NOTE = (
    "note: Negation check not run (arrives in S10): supported claims with located evidence are "
    "needs_review, never passed.\n"
)


@pytest.mark.parametrize(
    ("mode", "run_id", "pairs", "claims"),
    [
        (
            "strict",
            "b04294ccd9a244cb",
            "0, needs_review=3, failed=0, flagged=1",
            "0, needs_review=2, failed=0, flagged=1",
        ),
        (
            "over_eager",
            "b3c8cbab00ca88fd",
            "0, needs_review=1, failed=1, flagged=4",
            "0, needs_review=1, failed=1, flagged=4",
        ),
    ],
)
def test_fake_run_stdout_is_byte_exact(
    tmp_path: Path, mode: str, run_id: str, pairs: str, claims: str
) -> None:
    result = runner.invoke(app, ["run", "Q?", "--fake", "--mode", mode, "--out", str(tmp_path)])
    assert result.exit_code == 0
    assert result.stdout == (
        "FAKE RUN: fictional papers, scripted answer and verdicts. Not a result.\n"
        f"report: {tmp_path / run_id / 'report.json'}\n"
        f"pairs: passed={pairs}\nclaims: passed={claims}\n" + NOTE
    )
