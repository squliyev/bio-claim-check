"""I83: the UI's error copy covers every error a recorded command raises on purpose, and names only
documented codes; raw exception text never reaches the page."""

import re
from pathlib import Path

import pytest

from bio_claim_check.app.recorded import UI_ERRORS
from bio_claim_check.app.ui.error_copy import ERROR_COPY, GENERIC, message_for
from bio_claim_check.app.ui.protocol import AboutLoadError, LedgerError
from bio_claim_check.app.usecases.check_claim import CheckInputError
from bio_claim_check.app.usecases.proof_checkpoint import CheckpointError
from bio_claim_check.app.usecases.published_run import PublishedRunError
from bio_claim_check.common.errors import BccError

ROOT = Path(__file__).resolve().parents[4]
DOCUMENTED = frozenset(re.findall(r"^\| `([a-z_.]+)` \|", (ROOT / "docs/error-codes.md").read_text(), re.M))
PAGE_ERRORS = (*UI_ERRORS, PublishedRunError, LedgerError, AboutLoadError, CheckpointError)


def test_every_copy_key_is_a_documented_code() -> None:
    assert len(DOCUMENTED) > 40
    assert set(ERROR_COPY) <= DOCUMENTED


@pytest.mark.parametrize("error", PAGE_ERRORS, ids=lambda e: e.code)
def test_every_error_the_page_can_meet_has_copy(error: type[BccError]) -> None:
    assert error.code in ERROR_COPY


def test_the_copy_never_carries_the_exception_text() -> None:
    err = CheckInputError("PMID '<script>' at /Users/someone/var is not 1 to 9 digits")
    shown = message_for(err)
    assert shown == ERROR_COPY["check.input"]
    assert "<script>" not in shown
    assert "/Users" not in shown


def test_an_unknown_code_gets_the_generic_copy() -> None:
    class StrangeError(BccError):
        code = "strange.thing"

    assert message_for(StrangeError("internal detail")) == GENERIC
