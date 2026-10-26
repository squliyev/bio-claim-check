"""The shared loader refuses anything whose hash chain or kind does not hold. Each variant manifest is
re-hashed with `run_id_of`, so a refusal is reached through the chain, not around it."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.support.checks import CLAIM_TEXT, PMID, live_check
from tests.support.settings import make_settings

from bio_claim_check.app import recorded
from bio_claim_check.app.container import fake_check_claims, read_ledger, read_published_files
from bio_claim_check.app.recorded import record_check, record_question
from bio_claim_check.app.run_record import MANIFEST_FILE, CheckInputs, RunInputs, run_id_of
from bio_claim_check.app.usecases.check_claim import live_claim
from bio_claim_check.app.usecases.published_run import PublishedRunError, load_published, validate_run_id
from bio_claim_check.common.canonical_json import pretty_json_bytes
from bio_claim_check.features.contracts.labels import AnswerMode


def _check(tmp_path: Path) -> tuple[str, bytes, bytes]:
    run_id = record_check(fake_check_claims()[0], settings=None, var_dir=tmp_path).run_id
    return run_id, *read_published_files(tmp_path, run_id)


def _question(tmp_path: Path) -> tuple[str, bytes, bytes]:
    run_id = record_question(
        "Does OS-912 help?", AnswerMode.STRICT, 3, settings=None, var_dir=tmp_path
    ).run_id
    return run_id, *read_published_files(tmp_path, run_id)


def _variant(manifest: bytes, change: Callable[[dict[str, Any]], None]) -> tuple[str, bytes]:
    data = json.loads(manifest)
    change(data)
    raw = pretty_json_bytes(data)
    return run_id_of(raw), raw


@pytest.mark.parametrize("run_id", ["", "ABCDEF0123456789", "0123456789abcde", "../../etc/passwd", "0" * 17])
def test_a_malformed_run_id_is_refused(run_id: str) -> None:
    with pytest.raises(PublishedRunError, match="16 lowercase hex"):
        validate_run_id(run_id)


def test_a_manifest_copied_under_another_run_id_is_refused(tmp_path: Path) -> None:
    run_id, manifest, artifact = _check(tmp_path)
    other = _question(tmp_path)[0]
    with pytest.raises(PublishedRunError, match="does not hash to the run id"):
        load_published(other, manifest, artifact)
    assert load_published(run_id, manifest, artifact).run_id == run_id


def test_a_manifest_that_does_not_parse_is_refused() -> None:
    with pytest.raises(PublishedRunError, match="does not parse"):
        load_published("0" * 16, b"{", b"")


def test_an_altered_artifact_is_refused(tmp_path: Path) -> None:
    run_id, manifest, artifact = _check(tmp_path)
    with pytest.raises(PublishedRunError, match="does not match its manifest"):
        load_published(run_id, manifest, artifact.replace(b"OS-912", b"OS-913", 1))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_an_artifact_named_for_another_command_is_refused(tmp_path: Path) -> None:
    _, manifest, artifact = _check(tmp_path)
    run_id, variant = _variant(manifest, lambda d: d["artifact"].update(name="report.json"))
    with pytest.raises(PublishedRunError, match=r"`check` runs with report\.json cannot be shown"):
        load_published(run_id, variant, artifact)


def test_an_unknown_command_is_refused(tmp_path: Path) -> None:
    _, manifest, artifact = _question(tmp_path)
    run_id, variant = _variant(manifest, lambda d: d.update(command="traps"))
    with pytest.raises(PublishedRunError, match="cannot be shown"):
        load_published(run_id, variant, artifact)


def test_inputs_of_another_command_are_refused(tmp_path: Path) -> None:
    _, manifest, artifact = _question(tmp_path)

    def as_check(d: dict[str, Any]) -> None:
        d.update(command="check")
        d["artifact"]["name"] = "check.json"

    run_id, variant = _variant(manifest, as_check)
    with pytest.raises(PublishedRunError, match="inputs do not match its command"):
        load_published(run_id, variant, artifact)


def test_a_report_under_a_check_manifest_is_refused(tmp_path: Path) -> None:
    _, manifest, _ = _check(tmp_path)
    _, _, report = _question(tmp_path)
    run_id, variant = _variant(manifest, lambda d: d["artifact"].update(sha256=_sha(report)))
    with pytest.raises(PublishedRunError, match=r"check\.json is not a claim check"):
        load_published(run_id, variant, report)


def test_a_check_of_another_claim_is_refused(tmp_path: Path) -> None:
    _, manifest, artifact = _check(tmp_path)
    run_id, variant = _variant(manifest, lambda d: d["inputs"].update(claim_sha256=_sha(b"another claim")))
    with pytest.raises(PublishedRunError, match="does not check what its manifest names"):
        load_published(run_id, variant, artifact)
    run_id, variant = _variant(manifest, lambda d: d["inputs"].update(source_id="FAKE:2"))
    with pytest.raises(PublishedRunError, match="does not check what its manifest names"):
        load_published(run_id, variant, artifact)


def test_a_fake_manifest_over_a_live_artifact_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(recorded, "build_live_check_ports", live_check)
    settings = make_settings(var_dir=tmp_path)
    live = record_check(live_claim(CLAIM_TEXT, PMID), settings=settings, var_dir=tmp_path).run_id
    manifest, artifact = read_published_files(tmp_path, live)

    def as_fake(d: dict[str, Any]) -> None:
        d.update(provenance="fake", declared_llm=[], llm=[])

    run_id, variant = _variant(manifest, as_fake)
    with pytest.raises(PublishedRunError, match="says live, its manifest fake"):
        load_published(run_id, variant, artifact)


def test_run_inputs_keep_their_bytes_and_check_inputs_are_tagged() -> None:
    run = RunInputs(question_sha256=_sha(b"q"), mode=AnswerMode.STRICT, k=3).model_dump(mode="json")
    assert set(run) == {"question_sha256", "question_id", "mode", "k"}
    check = CheckInputs(claim_sha256=_sha(b"c"), source_id="MED:1").model_dump(mode="json")
    assert check == {"kind": "check", "claim_sha256": _sha(b"c"), "source_id": "MED:1"}


def test_the_reader_needs_exactly_one_viewable_artifact(tmp_path: Path) -> None:
    run_id, _, artifact = _check(tmp_path)
    folder = tmp_path / "runs" / run_id
    (folder / "report.json").write_bytes(artifact)
    with pytest.raises(PublishedRunError, match=r"expected one of report\.json, check\.json"):
        read_published_files(tmp_path, run_id)
    (folder / "report.json").unlink()
    (folder / MANIFEST_FILE).unlink()
    with pytest.raises(PublishedRunError, match="cannot read"):
        read_published_files(tmp_path, run_id)


def test_an_empty_var_dir_has_an_empty_ledger(tmp_path: Path) -> None:
    assert read_ledger(tmp_path) == b""
    (tmp_path / "ledger.jsonl").mkdir()
    with pytest.raises(PublishedRunError, match="cannot read"):
        read_ledger(tmp_path)
