"""The committed challenge result attests the current challenge set and judge (I72, ADR 0020).

Self-reported: this proves the recorded result is consistent with the set, the sealed dev dataset, the
judge code and the configured models, not that a model produced it. No skip: the files must exist.
"""

import pytest

from bio_claim_check.app.container import current_judge, read_dataset
from bio_claim_check.app.freeze import ACTIVE_FREEZE
from bio_claim_check.app.usecases.challenge import attestation_problems
from tests.support.paths import ROOT
from tests.support.settings import make_settings

pytestmark = pytest.mark.arch

CHALLENGE = ROOT / "challenge" / "dev-v1.jsonl"
RESULT = ROOT / "challenge" / "results" / f"{ACTIVE_FREEZE}.json"


def test_the_committed_challenge_result_attests_this_judge() -> None:
    judge = current_judge(make_settings())
    problems = attestation_problems(
        CHALLENGE.read_bytes(),
        RESULT.read_bytes(),
        read_dataset(ROOT / "datasets"),
        judge_sha256=judge.sha256,
        verifier=str(judge.verifier["deployment"]),
    )
    assert problems == []
