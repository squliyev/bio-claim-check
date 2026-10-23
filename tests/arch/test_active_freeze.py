"""The committed freeze records match their pins, and the code is still the active frozen judge (I73).

ADR 0020. No skip: the active record must exist. Any edit to a judge file, the models or the challenge
result fails here and names what changed; a new judge needs a new record, a new pin and an ADR.
"""

import hashlib

import pytest

from bio_claim_check.app.container import current_judge
from bio_claim_check.app.freeze import (
    ACTIVE_FREEZE,
    FREEZE_DIR,
    FROZEN,
    freeze_problems,
    freeze_record,
    unfrozen_audits,
)
from tests.support.paths import ROOT
from tests.support.settings import make_settings

pytestmark = pytest.mark.arch

RECORDS = ROOT / FREEZE_DIR
RESULT = ROOT / "challenge" / "dev-v1.result.json"


def test_every_freeze_record_is_pinned_and_unchanged() -> None:
    on_disk = {p.stem: hashlib.sha256(p.read_bytes()).hexdigest() for p in RECORDS.glob("*.json")}
    assert on_disk == dict(FROZEN)


def test_the_code_is_the_active_frozen_judge() -> None:
    current = freeze_record(ACTIVE_FREEZE, current_judge(make_settings()), RESULT.read_bytes())
    committed = (RECORDS / f"{ACTIVE_FREEZE}.json").read_bytes()
    assert freeze_problems(committed, current) == []


def test_every_committed_test_audit_was_made_under_a_freeze() -> None:
    audits = {p.name: p.read_bytes() for p in (ROOT / "datasets" / "audit" / "test").glob("*.json")}
    records = {p.name: p.read_bytes() for p in RECORDS.glob("*.json")}
    assert unfrozen_audits(audits, records) == []
