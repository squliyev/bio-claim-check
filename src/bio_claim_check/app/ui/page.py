"""[RING:app/ui] The Streamlit page: renders what `protocol` and `run_view` built, and nothing else.

Why: the demo needs a reader-facing view of a run: each claim's verdict and reason, with its evidence
marked in the abstract (roadmap B4, S17a). This is the one module that imports streamlit (I82). It holds no
logic: runs and checks go through `app.recorded` (the same path the CLI takes), files through
`app.container`, and every text it shows as HTML was escaped by `run_view` and goes through `st.html`, which
never parses Markdown. Errors show curated copy by code (`error_copy`), never exception text.
It starts from `UiSettings`, which needs no secrets; the full `Settings` is loaded only when a live or replay
action starts, so recorded runs, fictional mode and About work without a `.env` (R3). Under
`BCC_CACHE_MODE=read-only` the live action is a replay: the container then builds no LLM client and the
cache refuses misses (ADR 0009), so no click can reach a provider.
Must not: compute, judge or rescale anything; render text that `run_view` did not escape; use
Markdown with raw HTML; or call a provider in fictional mode.
"""

import argparse
import sys
from pathlib import Path
from typing import Final

import streamlit as st
from pydantic import ValidationError

from bio_claim_check.app.container import fake_check_claims, read_ledger, read_published_files
from bio_claim_check.app.recorded import UI_ERRORS, record_check, record_question
from bio_claim_check.app.settings import (
    CHECKPOINT_RESULT,
    Settings,
    UiSettings,
    load_settings,
    load_ui_settings,
)
from bio_claim_check.app.ui.error_copy import LIVE_UNAVAILABLE, message_for
from bio_claim_check.app.ui.protocol import (
    RUNS_LABEL,
    AboutLoadError,
    AboutView,
    LedgerError,
    list_runs,
    load_about,
)
from bio_claim_check.app.ui.run_view import ClaimView, PairView, RunView, view
from bio_claim_check.app.usecases.check_claim import live_claim
from bio_claim_check.app.usecases.proof_checkpoint import CheckpointError
from bio_claim_check.app.usecases.published_run import PublishedRunError, load_published
from bio_claim_check.engine.cache.policy import CacheMode
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.contracts.verdict import Claim

PAGE_ERRORS: Final = (*UI_ERRORS, PublishedRunError, LedgerError, AboutLoadError, CheckpointError)
"""Every coded error a page action can meet on purpose; each has curated copy (I83)."""

DISCLAIMER: Final = (
    "Abstracts only: the verifier reads abstracts, never full text. Every label is a model judgement or "
    "a scripted example, not expert review. Research software, not medical advice."
)
ASK, CHECK, TRUST, ABOUT = "Ask a question", "Check a claim", "Trust report", "About the verifier"
SECTIONS: Final = (ASK, CHECK, TRUST, ABOUT)
FICTIONAL: Final = "Fictional (offline, scripted)"
LIVE: Final = "Live (Europe PMC and the configured models)"
REPLAY: Final = "Replay (read-only cache; no provider is called)"
LAST_RUN: Final = "last_run_id"
BAD_UI_SETTINGS: Final = (
    "BCC_VAR_DIR or BCC_CACHE_MODE is set to a value the app cannot use; fix it and reload."
)


def _env_file(argv: list[str]) -> Path:
    """`page.py -- --env-file PATH`, as `bio-claim-check ui` passes it; `.env` by default."""
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    return parser.parse_known_args(argv)[0].env_file


def _header(section: str, ui: UiSettings) -> None:
    st.title("bio-claim-check")
    st.caption(section)
    st.info(DISCLAIMER)
    if ui.cache_mode is CacheMode.READ_ONLY:
        st.caption("Read-only mode: live actions replay cached responses only.")


def _sources(ui: UiSettings) -> tuple[str, str]:
    return FICTIONAL, REPLAY if ui.cache_mode is CacheMode.READ_ONLY else LIVE


def _settings(env_file: Path) -> Settings | None:
    try:
        return load_settings(env_file)
    except (ValidationError, OSError, UnicodeDecodeError):
        st.error(LIVE_UNAVAILABLE)
        return None


def _show_run(ui: UiSettings, run_id: str) -> None:
    try:
        run = load_published(run_id, *read_published_files(ui.var_dir, run_id))
    except PAGE_ERRORS as err:
        st.error(message_for(err))
        return
    _render(view(run))


def _render(run: RunView) -> None:
    st.html(f"<p><strong>{run.notice_html}</strong></p>")
    st.html(f"<h3>{run.heading_html}</h3>")
    st.html(f"<p><small>{run.record_html}</small></p>")
    for line in run.models_html:
        st.html(f"<p><small>{line}</small></p>")
    if run.same_family_warning:
        st.warning("One model family both answered and judged: its blind spots may agree.")
    for claim in run.claims:
        _render_claim(claim)
    if run.findings_html:
        st.subheader("Findings")
        for finding in run.findings_html:
            st.html(f"<p>{finding}</p>")


def _render_claim(claim: ClaimView) -> None:
    st.divider()
    st.html(f"<p><strong>{claim.claim_id_html}</strong> [{claim.disposition}] {claim.text_html}</p>")
    for pair in claim.pairs:
        _render_pair(pair)


def _render_pair(pair: PairView) -> None:
    year = f" ({pair.year})" if pair.year else ""
    title = f" {pair.title_html}{year}" if pair.title_html else ""
    st.html(f"<p><code>{pair.source_id_html}</code>{title} [{pair.disposition}]</p>")
    if pair.label is not None:
        reason = f", {pair.overstated_reason}" if pair.overstated_reason else ""
        st.html(f"<p>Label: <strong>{pair.label}</strong>{reason}. Evidence: {pair.evidence_status}.</p>")
    if pair.reason_html is not None:
        st.html(f"<p>Reason: {pair.reason_html}</p>")
    if pair.quote_html is not None:
        st.html(f"<blockquote>{pair.quote_html}</blockquote>")
    if pair.failure is not None:
        st.html(f"<p>No verdict: {pair.failure}.</p>")
    if pair.abstract_html:
        with st.expander("Abstract" + (" (evidence marked)" if pair.highlighted else "")):
            st.html(f"<p>{pair.abstract_html}</p>")


def _ask(ui: UiSettings, env_file: Path) -> None:
    question = st.text_input("Question", value="Does OS-912 help?")
    mode = st.radio("Answer mode", [m.value for m in AnswerMode], horizontal=True)
    k = st.number_input("Papers (k)", min_value=1, max_value=10, value=3, step=1)
    source = st.radio("Source", _sources(ui), key="ask_source")
    if st.button("Run", key="ask_run"):
        settings = None if source == FICTIONAL else _settings(env_file)
        if source == FICTIONAL or settings is not None:
            with st.spinner("Answering and checking every claim…"):
                try:
                    recorded = record_question(
                        question, AnswerMode(mode), int(k), settings=settings, var_dir=ui.var_dir
                    )
                except PAGE_ERRORS as err:
                    st.error(message_for(err))
                else:
                    st.session_state[LAST_RUN] = recorded.run_id
    if run_id := st.session_state.get(LAST_RUN):
        _show_run(ui, str(run_id))


def _fictional_label(claim: Claim) -> str:
    return f"{claim.id}: {claim.text} ({claim.cites[0]})"


def _check(ui: UiSettings, env_file: Path) -> None:
    source = st.radio("Source", _sources(ui), key="check_source")
    if source == FICTIONAL:
        examples = fake_check_claims()
        chosen = st.selectbox("Fictional claim", examples, format_func=_fictional_label)
        if st.button("Check", key="check_fake"):
            _record_check(ui, chosen, None)
    else:
        text = st.text_area("Claim", max_chars=1000)
        pmid = st.text_input("PMID of the paper the claim cites")
        if st.button("Check", key="check_live"):
            try:
                claim = live_claim(text, pmid)
            except PAGE_ERRORS as err:
                st.error(message_for(err))
            else:
                if (settings := _settings(env_file)) is not None:
                    _record_check(ui, claim, settings)
    if run_id := st.session_state.get(f"{LAST_RUN}_check"):
        _show_run(ui, str(run_id))


def _record_check(ui: UiSettings, claim: Claim, settings: Settings | None) -> None:
    with st.spinner("Fetching the paper and checking the claim…"):
        try:
            recorded = record_check(claim, settings=settings, var_dir=ui.var_dir)
        except PAGE_ERRORS as err:
            st.error(message_for(err))
        else:
            st.session_state[f"{LAST_RUN}_check"] = recorded.run_id


def _trust(ui: UiSettings) -> None:
    try:
        runs = list_runs(read_ledger(ui.var_dir))
    except PAGE_ERRORS as err:
        st.error(message_for(err))
        return
    if not runs:
        st.write("No recorded runs yet. Ask a question or check a claim first.")
        return
    st.caption(RUNS_LABEL)
    chosen = st.selectbox("Recorded run", runs, format_func=lambda r: r.label)
    _show_run(ui, chosen.run_id)


def _table(rows: list[dict[str, object]]) -> None:
    st.table(rows)  # pyright: ignore[reportUnknownMemberType] - streamlit's signature leaves one pandas type Unknown


def _about() -> None:
    try:
        about = load_about(CHECKPOINT_RESULT)
    except PAGE_ERRORS as err:
        st.error(message_for(err))
        return
    _render_about(about)


def _render_about(about: AboutView) -> None:
    st.write(about.label)
    if about.verdict == "GO":
        st.success(about.framing)
    else:
        st.warning(about.framing)
    if about.verdict is not None:
        st.write(f"Verdict under the predeclared rule `{about.policy}` (ADR 0024): **{about.verdict}**")
        _table(
            [
                {"condition": r.name, "count": f"{r.value} of {r.denominator}", "bar": r.bound, "met": r.met}
                for r in about.rules
            ]
        )
    st.write(f"Verifier: `{about.verifier}`. Counts are k of n, never rates.")
    if about.writer_family_flag:
        st.warning("The trap writer and the verifier share a model family.")
    st.subheader("Disposition counts")
    _table(
        [
            {
                "kind": r.kind,
                "role": r.role,
                "generator": r.generator,
                "n": r.n,
                "passed": r.passed,
                "needs_review": r.needs_review,
                "flagged": r.flagged,
                "failed": r.failed,
                "exact": r.exact,
            }
            for r in about.rows
        ]
    )
    st.subheader("Trap by parent (rows: trap; columns: its parent)")
    for pair in about.pairs:
        st.caption(
            f"{pair.kind}, {pair.generator}: n = {pair.n}; trap flagged and parent passed: "
            f"{pair.discriminated} of {pair.n}"
        )
        _table(
            [
                {"trap \\ parent": trap, **dict(zip(about.dispositions, row, strict=True))}
                for trap, row in zip(about.dispositions, pair.table, strict=True)
            ]
        )


def main(argv: list[str]) -> None:
    env_file = _env_file(argv)
    try:
        ui = load_ui_settings(env_file)
    except (ValidationError, OSError, UnicodeDecodeError):
        st.error(BAD_UI_SETTINGS)
        return
    section = st.sidebar.radio("Section", SECTIONS)
    _header(section, ui)
    if section == ASK:
        _ask(ui, env_file)
    elif section == CHECK:
        _check(ui, env_file)
    elif section == TRUST:
        _trust(ui)
    else:
        _about()


if __name__ == "__main__":  # `streamlit run` executes this file as __main__; importing it renders nothing
    main(sys.argv[1:])
