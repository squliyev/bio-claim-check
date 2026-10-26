"""AppTest smoke tests of the Streamlit page (S17a exit criterion): every section renders offline, without a
`.env`, with the disclaimer; fictional runs and checks render; errors show curated copy; user text is
escaped end to end; read-only mode offers a replay instead of a live call."""

import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from bio_claim_check.app import container, recorded
from bio_claim_check.app.cli import UI_PAGE
from bio_claim_check.app.container import read_ledger
from bio_claim_check.app.settings import CHECKPOINT_RESULT
from bio_claim_check.app.ui.error_copy import ERROR_COPY, LIVE_UNAVAILABLE
from bio_claim_check.app.ui.page import (
    ABOUT,
    ASK,
    CHECK,
    DISCLAIMER,
    FICTIONAL,
    LIVE,
    PAGE_ERRORS,
    REPLAY,
    SECTIONS,
    TRUST,
)
from bio_claim_check.app.ui.protocol import ADJUST_LABEL, list_runs, load_about
from bio_claim_check.features.contracts.rulepack import RulePackError

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _checkpoint_result() -> None:
    """Each test runs in an empty working directory (tests/conftest.py); About reads the committed result."""
    target = Path.cwd() / CHECKPOINT_RESULT
    target.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / CHECKPOINT_RESULT, target)


def _app(section: str = ASK) -> AppTest:
    app = AppTest.from_file(str(UI_PAGE), default_timeout=60)
    app.run()
    if section != ASK:
        app.sidebar.radio[0].set_value(section).run()
    assert not app.exception
    return app


def _html(app: AppTest) -> list[str]:
    elements = app.get("html")
    return [str(e.proto.body) for e in elements]


def _errors(app: AppTest) -> list[str]:
    return [str(e.value) for e in app.error]


@pytest.mark.parametrize("section", SECTIONS)
def test_every_section_renders_without_a_env_file_and_shows_the_disclaimer(section: str) -> None:
    app = _app(section)
    assert [i.value for i in app.info] == [DISCLAIMER]
    assert not app.error


def test_a_fictional_run_renders_its_claims_with_marked_evidence() -> None:
    app = _app()
    app.radio(key="ask_source").set_value(FICTIONAL).run()
    app.button(key="ask_run").click().run()
    assert not app.exception
    assert not app.error
    html = _html(app)
    assert any("FAKE RUN" in h for h in html)
    assert any("<mark>" in h for h in html)
    (run,) = list_runs(read_ledger(Path("var")))
    assert any(run.run_id in h for h in html)


def test_a_fictional_check_renders_and_appears_in_the_trust_report() -> None:
    app = _app(CHECK)
    app.radio(key="check_source").set_value(FICTIONAL).run()
    app.button(key="check_fake").click().run()
    assert not app.error
    assert any("FAKE CHECK" in h for h in _html(app))
    (run,) = list_runs(read_ledger(Path("var")))
    app.sidebar.radio[0].set_value(TRUST).run()
    assert app.selectbox[0].value == run
    assert any(run.run_id in h for h in _html(app))


def test_user_text_is_escaped_end_to_end() -> None:
    app = _app()
    app.text_input[0].set_value("<script>alert(1)</script> & co?")
    app.button(key="ask_run").click().run()
    html = _html(app)
    assert all("<script>" not in h for h in html)
    assert "<h3>&lt;script&gt;alert(1)&lt;/script&gt; &amp; co?</h3>" in html


def test_an_error_shows_its_curated_copy_not_the_exception_text() -> None:
    app = _app()
    app.text_input[0].set_value("   ")
    app.button(key="ask_run").click().run()
    assert _errors(app) == [ERROR_COPY["run.input"]]


def test_a_bad_pmid_is_refused_before_any_settings_or_network() -> None:
    app = _app(CHECK)
    app.radio(key="check_source").set_value(LIVE).run()
    app.text_area[0].set_value("Drug X cures everything.")
    app.text_input[0].set_value("PMID: 12a")
    app.button(key="check_live").click().run()
    assert _errors(app) == [ERROR_COPY["check.input"]]


def test_live_without_settings_says_so_and_records_nothing() -> None:
    app = _app(CHECK)
    app.radio(key="check_source").set_value(LIVE).run()
    app.text_area[0].set_value("Drug X cures everything.")
    app.text_input[0].set_value("12345678")
    app.button(key="check_live").click().run()
    assert _errors(app) == [LIVE_UNAVAILABLE]
    assert read_ledger(Path("var")) == b""


def test_read_only_mode_offers_a_replay_instead_of_a_live_call(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _app().radio(key="ask_source").options == [FICTIONAL, LIVE]
    monkeypatch.setenv("BCC_CACHE_MODE", "read-only")
    for section, key in ((ASK, "ask_source"), (CHECK, "check_source")):
        assert _app(section).radio(key=key).options == [FICTIONAL, REPLAY]


def test_a_busy_recorder_shows_the_busy_copy() -> None:
    lock = recorded._RECORD_LOCK  # pyright: ignore[reportPrivateUsage] - held as a concurrent session would
    assert lock.acquire(blocking=False)
    try:
        app = _app()
        app.button(key="ask_run").click().run()
        assert _errors(app) == [ERROR_COPY["runs.busy"]]
    finally:
        lock.release()


def test_a_corrupt_ledger_shows_the_ledger_copy() -> None:
    Path("var").mkdir()
    Path("var/ledger.jsonl").write_bytes(b"not a row\n")
    assert _errors(_app(TRUST)) == [ERROR_COPY["ui.ledger"]]


def test_the_about_page_shows_every_table_and_the_adjust_framing() -> None:
    app = _app(ABOUT)
    about = load_about(CHECKPOINT_RESULT)
    assert [w.value for w in app.warning] == [ADJUST_LABEL]
    assert len(app.table) == 2 + len(about.pairs)  # the rule lines, the counts, one table per pair row


def test_a_missing_about_result_shows_the_about_copy() -> None:
    (Path.cwd() / CHECKPOINT_RESULT).unlink()
    assert _errors(_app(ABOUT)) == [ERROR_COPY["ui.about"]]


def test_every_error_the_page_catches_has_copy() -> None:
    assert {e.code for e in PAGE_ERRORS} <= set(ERROR_COPY)


def test_a_broken_rule_pack_shows_curated_copy_not_a_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> None:
        raise RulePackError(["secret detail"])

    monkeypatch.setattr(container, "default_rulepack_hashed", broken)
    app = _app()
    app.button(key="ask_run").click().run()
    assert not app.exception
    assert _errors(app) == [ERROR_COPY["contracts.rule_pack"]]
    assert all("secret detail" not in h for h in _html(app))
