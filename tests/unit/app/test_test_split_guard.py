"""Live `check` and `run` keep the sealed test split closed: refused before any fetch or LLM call (I84)."""

import shutil
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import override

import pytest
from tests.support.checks import CLAIM_TEXT, SEALED_ID, SEALED_PMID, live_check, live_check_ports
from tests.support.paths import SEALED
from tests.support.settings import make_settings
from typer.testing import CliRunner

from bio_claim_check.app import cli, recorded
from bio_claim_check.app.container import (
    DatasetReadError,
    build_fake_run_ports,
    build_live_check_ports,
    build_live_run_ports,
    read_dataset,
    sealed_test_ids,
)
from bio_claim_check.app.recorded import UI_ERRORS
from bio_claim_check.app.ui.error_copy import ERROR_COPY
from bio_claim_check.app.usecases.check_claim import HeldOutSourceError, check_claim
from bio_claim_check.app.usecases.run import run_question
from bio_claim_check.engine.cache.policy import CacheMode
from bio_claim_check.features.contracts.corpus import SourceEntry
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.verdict import Claim
from bio_claim_check.features.corpus.layout import DEV_SOURCES, TEST_SOURCES
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.retrieval.in_memory_literature_source import FAKE_CORPUS
from bio_claim_check.features.retrieval.models import RetractionStatus

pytestmark = pytest.mark.unit


class NoFetch(BaseLiteratureSource):
    """Fails the test if the guard lets a request through."""

    @override
    def search(self, question: str, *, limit: int) -> tuple[Paper, ...]:
        raise AssertionError("searched")

    @override
    def retraction_status(self, source_ids: Sequence[SourceId]) -> tuple[RetractionStatus, ...]:
        raise AssertionError("asked for retractions")

    @override
    def fetch(self, source_id: SourceId) -> Paper:
        raise AssertionError(f"fetched {source_id}")


def _entries(name: str) -> list[SourceEntry]:
    lines = read_dataset(SEALED)[name].decode().splitlines()
    return [SourceEntry.model_validate_json(line) for line in lines]


def test_a_check_on_a_sealed_paper_is_refused_before_the_fetch() -> None:
    ports = live_check_ports()

    ports = replace(ports, literature=NoFetch())
    with pytest.raises(HeldOutSourceError, match="sealed test split") as caught:
        check_claim(ports, Claim(id="c1", text=CLAIM_TEXT, cites=(SEALED_ID,)))
    assert caught.value.code == "check.test_split"


def test_a_run_that_retrieves_a_sealed_paper_is_refused_before_the_answer() -> None:
    sealed = FAKE_CORPUS[1].source_id

    ports = replace(build_fake_run_ports(), closed_ids=frozenset({sealed}))
    with pytest.raises(HeldOutSourceError) as caught:
        run_question(ports, "Does OS-912 work?", AnswerMode.STRICT, k=4)
    assert caught.value.source_ids == (sealed,)


def test_the_closed_set_is_every_test_source_and_cluster_and_no_dev_source() -> None:
    test = _entries(TEST_SOURCES)
    closed = sealed_test_ids(SEALED)
    assert closed == {i for e in test for i in (e.source_id, e.cluster_id)}
    assert len(closed) >= len(test) > 0
    assert not closed & {e.source_id for e in _entries(DEV_SOURCES)}


def test_a_dataset_that_fails_its_seal_fails_closed(tmp_path: Path) -> None:
    copy = tmp_path / "datasets"
    shutil.copytree(SEALED, copy)
    lines = (copy / TEST_SOURCES).read_text().splitlines()
    (copy / TEST_SOURCES).write_text("\n".join(lines[1:]) + "\n")
    with pytest.raises(DatasetReadError, match="not intact"):
        sealed_test_ids(copy)
    with pytest.raises(DatasetReadError, match="not a folder"):
        sealed_test_ids(tmp_path / "missing")


def test_live_check_ports_carry_the_closed_set_and_fail_closed_without_it(tmp_path: Path) -> None:
    settings = make_settings(cache_mode=CacheMode.READ_ONLY, var_dir=tmp_path)
    with build_live_check_ports(settings, None, dataset=SEALED) as live:
        assert live.ports.closed_ids == sealed_test_ids(SEALED)
    with pytest.raises(DatasetReadError), build_live_check_ports(settings, None, dataset=tmp_path / "none"):
        pass


def test_live_run_ports_carry_the_closed_set_of_the_dataset_they_are_given(tmp_path: Path) -> None:
    settings = make_settings(cache_mode=CacheMode.READ_ONLY, var_dir=tmp_path)
    with build_live_run_ports(settings, AnswerMode.STRICT, None, dataset=SEALED) as live:
        assert live.ports.closed_ids == sealed_test_ids(SEALED)


def test_a_broken_dataset_is_reported_before_any_other_live_setup_error(tmp_path: Path) -> None:
    settings = make_settings(cache_mode=CacheMode.READ_ONLY, var_dir=tmp_path, verifier_model="no-such-model")
    missing = tmp_path / "none"
    with (
        pytest.raises(DatasetReadError),
        build_live_run_ports(settings, AnswerMode.STRICT, None, dataset=missing),
    ):
        pass
    with pytest.raises(DatasetReadError), build_live_check_ports(settings, None, dataset=missing):
        pass


def test_the_cli_refuses_a_sealed_pmid_as_an_input_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BCC_CONTACT_EMAIL", "someone@example.org")
    monkeypatch.setenv("BCC_VAR_DIR", str(tmp_path / "var"))
    monkeypatch.setattr(recorded, "build_live_check_ports", live_check)
    result = CliRunner().invoke(
        cli.app, ["check", CLAIM_TEXT, "--pmid", SEALED_PMID, "--env-file", str(tmp_path / "none.env")]
    )
    assert result.exit_code == cli.ExitCode.INPUT
    assert "sealed test split" in result.stderr
    assert result.stdout == ""


def test_the_ui_has_curated_copy_for_the_guard() -> None:
    assert {HeldOutSourceError, DatasetReadError} <= set(UI_ERRORS)
    assert {"check.test_split", "app.dataset_read"} <= ERROR_COPY.keys()
