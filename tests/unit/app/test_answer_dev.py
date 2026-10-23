"""`answer dev`: seal first, dev questions only, the dev pool only, then the deterministic checks."""

import contextlib
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from typing import override

import pytest
from tests.support.corpus import SPEC_FILE, QueryLiteratureSource, dataset_files, world
from tests.support.events import MODEL, T0
from typer.testing import CliRunner

from bio_claim_check.app import cli
from bio_claim_check.app.container import load_corpus_spec
from bio_claim_check.app.settings import Settings
from bio_claim_check.app.usecases.answer_dev import (
    CallTally,
    DevAnswerInputError,
    DevAnswerPorts,
    EmptyDevPoolError,
    answer_dev,
    tally_calls,
)
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.llm_events import LlmCallFailed, LlmCallFinished
from bio_claim_check.engine.events.stage_events import StageStarted
from bio_claim_check.engine.llm.errors import (
    LlmPromptFilteredError,
    LlmProviderError,
    LlmRequestError,
    LlmTransportError,
    LlmUnexpectedResponseError,
)
from bio_claim_check.engine.llm.model_spec import ModelSpec
from bio_claim_check.features.answer.scripted_answerer import ScriptedAnswerer
from bio_claim_check.features.contracts.answer import Answer
from bio_claim_check.features.contracts.finding import FindingKind
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.verdict import Claim
from bio_claim_check.features.corpus.layout import MANIFEST, SEALED
from bio_claim_check.features.corpus.seal import sealed_bytes

pytestmark = pytest.mark.unit
runner = CliRunner()
SPEC = load_corpus_spec(SPEC_FILE)
DEV_Q = "fx-glp1-q1"
CLAIMS = (
    Claim(id="c1", text="OS-912 slowed decline in mice.", cites=("MED:5", "MED:99")),
    Claim(id="c2", text="This drug is safe.", cites=("MED:11",)),
)


class RecordingAnswerer(ScriptedAnswerer):
    def __init__(self) -> None:
        super().__init__(dict.fromkeys(AnswerMode, CLAIMS))
        self.papers: list[tuple[Paper, ...]] = []

    @override
    def answer(self, question: str, papers: tuple[Paper, ...], mode: AnswerMode) -> Answer:
        self.papers.append(papers)
        return super().answer(question, papers, mode)


def _sealed() -> dict[str, bytes]:
    files = dataset_files()
    return {**files, SEALED: sealed_bytes(files[MANIFEST])}


def _ports(pools: dict[str, tuple[Paper, ...]] | None = None) -> tuple[DevAnswerPorts, QueryLiteratureSource]:
    source = QueryLiteratureSource(world() if pools is None else pools)
    return DevAnswerPorts(source=source, answerer=RecordingAnswerer()), source


def test_answers_from_the_dev_pool_and_runs_both_checks_in_order() -> None:
    ports, source = _ports()
    result = answer_dev(ports, _sealed(), SPEC, DEV_Q, AnswerMode.STRICT, k=8)
    assert source.calls == [(result.question.query, SPEC.pool_hits)]
    assert isinstance(ports.answerer, RecordingAnswerer)
    assert [[p.source_id for p in papers] for papers in ports.answerer.papers] == [["MED:5", "MED:11"]]
    assert (result.answer.question, result.answer.mode) == (result.question.text, AnswerMode.STRICT)
    assert [(f.kind, f.claim_id, f.source_id) for f in result.findings] == [
        (FindingKind.INVENTED_CITATION, "c1", "MED:99"),
        (FindingKind.DANGLING_REFERENCE, "c2", None),
    ]


def test_an_unsealed_dataset_is_refused_before_any_fetch() -> None:
    ports, source = _ports()
    with pytest.raises(DevAnswerInputError) as err:
        answer_dev(ports, dataset_files(), SPEC, DEV_Q, AnswerMode.STRICT, k=8)
    assert err.value.problems == ("the dataset is not intact and sealed:", f"{SEALED} is missing")
    assert source.calls == []


@pytest.mark.parametrize(
    ("question_id", "message"),
    [
        ("nope", "no question 'nope' in the dataset"),
        ("fx-glp1-q2", "fx-glp1-q2 is a test question; only dev questions may be used"),
    ],
)
def test_unknown_and_test_questions_are_refused_before_any_fetch(question_id: str, message: str) -> None:
    ports, source = _ports()
    with pytest.raises(DevAnswerInputError) as err:
        answer_dev(ports, _sealed(), SPEC, question_id, AnswerMode.STRICT, k=8)
    assert err.value.problems == (message,)
    assert source.calls == []


def test_an_empty_dev_pool_is_refused_before_answering() -> None:
    ports, _ = _ports({})
    with pytest.raises(EmptyDevPoolError, match=DEV_Q):
        answer_dev(ports, _sealed(), SPEC, DEV_Q, AnswerMode.STRICT, k=8)
    assert isinstance(ports.answerer, RecordingAnswerer)
    assert ports.answerer.papers == []


@pytest.mark.parametrize("k", [0, True, 1.5, "8"])
def test_a_bad_k_is_refused(k: int) -> None:
    ports, source = _ports()
    with pytest.raises(ValueError, match="k must be a positive int"):
        answer_dev(ports, _sealed(), SPEC, DEV_Q, AnswerMode.STRICT, k=k)
    assert source.calls == []


def _finished(
    *, cache_hit: bool, tokens: int, at: datetime = T0, reasoning: int | None = -1
) -> LlmCallFinished:
    return LlmCallFinished(
        at=at,
        agent="answer_strict",
        model=MODEL,
        attempt=1,
        finish_reason="stop",
        cache_hit=cache_hit,
        served_model="m",
        input_tokens=tokens,
        output_tokens=tokens,
        reasoning_tokens=(None if cache_hit else tokens) if reasoning == -1 else reasoning,
        cached_input_tokens=0,
    )


def test_tally_counts_tokens_of_live_calls_only() -> None:
    events = (
        StageStarted(at=T0, stage="answer"),
        _finished(cache_hit=False, tokens=10),
        _finished(cache_hit=True, tokens=1000),
        _finished(cache_hit=False, tokens=5),
    )
    assert tally_calls(events) == CallTally(
        live_calls=2, cached_calls=1, input_tokens=15, output_tokens=15, reasoning_tokens=15
    )


def test_tally_counts_failed_calls_and_unreported_reasoning_never_as_zero() -> None:
    failed = LlmCallFailed(
        at=T0, agent="answer_strict", model=MODEL, error_code="llm.transport", kind=None, attempts=1
    )
    events = (_finished(cache_hit=False, tokens=4, reasoning=None), failed)
    assert tally_calls(events) == CallTally(
        live_calls=1, failed_calls=1, input_tokens=4, output_tokens=4, reasoning_unreported=1
    )


# --- CLI ------------------------------------------------------------------------------------------


def _write(folder: Path, files: dict[str, bytes]) -> Path:
    for name, data in files.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return folder


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BCC_CONTACT_EMAIL", "someone@example.org")
    monkeypatch.setenv("BCC_VAR_DIR", str(tmp_path / "var"))

    @contextlib.contextmanager
    def ports(settings: Settings, spec: ModelSpec, emitter: EventEmitter | None) -> Generator[DevAnswerPorts]:
        del settings, spec
        assert emitter is not None
        emitter.emit(lambda at: _finished(cache_hit=False, tokens=7, at=at))
        yield _ports()[0]

    monkeypatch.setattr(cli, "build_dev_answer_ports", ports)


def _invoke(tmp_path: Path, files: dict[str, bytes], *argv: str) -> tuple[int, str, str]:
    folder = _write(tmp_path / "ds", files)
    env = str(tmp_path / "none.env")
    result = runner.invoke(cli.app, ["answer", "dev", *argv, "--dataset", str(folder), "--env-file", env])
    if result.exception and not isinstance(result.exception, SystemExit):
        raise result.exception
    return result.exit_code, result.stdout, result.stderr


@pytest.mark.usefixtures("scripted")
def test_cli_prints_claims_findings_drops_and_usage(tmp_path: Path) -> None:
    code, out, err = _invoke(tmp_path, _sealed(), DEV_Q, "--k", "8")
    assert code == 0, err
    assert f"{DEV_Q} (strict): 2 paper(s); dropped: not_in_pool=0, not_dev=3, hash_drift=0" in out
    assert "  c1 [MED:5, MED:99] OS-912 slowed decline in mice.\n" in out
    assert "findings: 2\n" in out
    assert "  dangling_reference c2: " in out
    assert "warning: only 2 usable dev paper(s), fewer than k=8" in err
    assert "dropped: not_in_pool=0, not_dev=3, hash_drift=0, missing_expected=0, beyond_k=0\n" in out
    assert (
        "llm calls: live=1 cache_hit=0 failed=0; live tokens in=7 out=7 reasoning=7 "
        "(unreported on 0 call(s)); failed calls may be billed, usage unknown; money: unpriced"
    ) in err


class _FailingAnswerer(ScriptedAnswerer):
    def __init__(self, error: Exception) -> None:
        super().__init__(dict.fromkeys(AnswerMode, CLAIMS))
        self._error = error

    @override
    def answer(self, question: str, papers: tuple[Paper, ...], mode: AnswerMode) -> Answer:
        raise self._error


@pytest.mark.parametrize(
    "error",
    [
        LlmTransportError(deployment="d", status=None, attempts=3, reason="timeout"),
        LlmProviderError(deployment="d", status=401, provider_code="auth"),
        LlmPromptFilteredError(deployment="d"),
        LlmRequestError("d: unsupported"),
        LlmUnexpectedResponseError("d: unknown shape"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_cli_maps_every_provider_failure_to_the_provider_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Exception
) -> None:
    monkeypatch.setenv("BCC_CONTACT_EMAIL", "someone@example.org")
    monkeypatch.setenv("BCC_VAR_DIR", str(tmp_path / "var"))

    @contextlib.contextmanager
    def ports(settings: Settings, spec: ModelSpec, emitter: EventEmitter | None) -> Generator[DevAnswerPorts]:
        del settings, spec, emitter
        yield DevAnswerPorts(source=_ports()[1], answerer=_FailingAnswerer(error))

    monkeypatch.setattr(cli, "build_dev_answer_ports", ports)
    code, _, err = _invoke(tmp_path, _sealed(), DEV_Q)
    assert code == cli.ExitCode.PROVIDER
    assert "llm calls: live=0" in err


@pytest.mark.usefixtures("scripted")
def test_cli_maps_an_unsealed_dataset_and_a_test_question_to_exit_codes(tmp_path: Path) -> None:
    assert _invoke(tmp_path / "a", dataset_files(), DEV_Q)[0] == cli.ExitCode.DATASET
    code, _, err = _invoke(tmp_path / "b", _sealed(), "fx-glp1-q2")
    assert code == cli.ExitCode.INPUT
    assert "only dev questions may be used" in err
