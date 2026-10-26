"""[TEST SUPPORT] A scripted live `run`: the real answerer, verifier and cache on a scripted provider.

`Provider.ports` stands in for `build_live_run_ports` (patched into the CLI), so tests exercise the real
agents and record path without a network; one cache is shared by every command a test runs, so a
read-only replay can be compared byte for byte.
"""

import contextlib
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from bio_claim_check.app import cli, recorded
from bio_claim_check.app.container import LiveRun, build_answerer, default_rulepack_hashed
from bio_claim_check.app.models import model_catalog
from bio_claim_check.app.run_record import DeclaredLlm
from bio_claim_check.app.settings import Settings
from bio_claim_check.app.usecases.run import RunPorts
from bio_claim_check.common.errors import BccError
from bio_claim_check.engine.cache.in_memory_cache import InMemoryCache
from bio_claim_check.engine.cache.policy import CacheMode
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.llm.caching_llm_client import CachingLlmClient
from bio_claim_check.engine.llm.messages import FinishReason, LlmResponse
from bio_claim_check.engine.llm.model_spec import ModelSpec
from bio_claim_check.engine.llm.scripted_llm_client import ScriptedLlmClient
from bio_claim_check.features.answer.strict_answer_llm_agent import StrictAnswerLlmAgent
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.report.models import ModelUse, RunModels
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.retrieval.in_memory_literature_source import InMemoryLiteratureSource
from bio_claim_check.features.verify.llm_verifier import LlmVerifier
from bio_claim_check.features.verify.verify_llm_agent import VerifyLlmAgent
from tests.support.llm import response
from tests.support.papers import paper

runner = CliRunner()

GPT = model_catalog().lookup("gpt-6.1-sol")
CLAUDE = model_catalog().lookup("claude-opus-4-8")
QUESTION = "Does OS-912 slow decline?"
HEDGED = paper(11, abstract="Mice received the drug. Memory improved. These findings suggest a benefit.")
PAPERS = (paper(1), HEDGED)
ANSWER = (
    '{"claims": [{"text": "OS-912 improved memory.", "cites": ["MED:11", "MED:99"]}, '
    '{"text": "OS-912 helps patients.", "cites": ["MED:1"]}]}'
)
SUPPORTED = (
    '{"label": "supported", "overstated_reason": null, "evidence": "Memory improved.", "reason": "Stated."}'
)
TRUNCATED = response("{", finish=FinishReason.LENGTH)


class Provider:
    """One scripted provider and one cache, shared by every command a test runs."""

    def __init__(self, *replies: LlmResponse | BccError, verifier: ModelSpec = CLAUDE) -> None:
        self.client = ScriptedLlmClient(replies)
        self.cache = InMemoryCache()
        self.verifier = verifier
        self.source: BaseLiteratureSource = InMemoryLiteratureSource(PAPERS)

    @contextlib.contextmanager
    def ports(self, settings: Settings, mode: AnswerMode, emitter: EventEmitter | None) -> Generator[LiveRun]:
        live = None if settings.cache_mode is CacheMode.READ_ONLY else self.client
        client = CachingLlmClient(live, self.cache, settings.cache_mode)
        rules = default_rulepack_hashed()
        declared = (
            DeclaredLlm(
                agent=StrictAnswerLlmAgent.name,
                provider=GPT.provider.value,
                deployment=GPT.deployment,
                model_version=GPT.model_version,
                prompt_sha256=StrictAnswerLlmAgent.prompt.sha256,
            ),
            DeclaredLlm(
                agent=VerifyLlmAgent.name,
                provider=self.verifier.provider.value,
                deployment=self.verifier.deployment,
                model_version=self.verifier.model_version,
                prompt_sha256=VerifyLlmAgent.prompt.sha256,
            ),
        )
        assert mode is AnswerMode.STRICT
        yield LiveRun(
            ports=RunPorts(
                literature=self.source,
                answerer=build_answerer(client, GPT, emitter),
                verifier=LlmVerifier(VerifyLlmAgent(client, self.verifier, emitter=emitter)),
                rules=rules.pack,
                provenance="live",
                rules_sha256=rules.sha256,
                models=RunModels(
                    answerer=ModelUse(deployment=GPT.deployment, family=GPT.family),
                    verifier=ModelUse(deployment=self.verifier.deployment, family=self.verifier.family),
                ),
                emitter=emitter,
            ),
            declared_llm=declared,
        )


def use(monkeypatch: pytest.MonkeyPatch, provider: Provider) -> Provider:
    monkeypatch.setattr(cli, "build_live_run_ports", provider.ports)  # `run --dev`
    monkeypatch.setattr(recorded, "build_live_run_ports", provider.ports)  # `run`, via the shared path
    return provider


def invoke(tmp_path: Path, *argv: str) -> tuple[int, str, str]:
    result = runner.invoke(cli.app, [*argv, "--env-file", str(tmp_path / "none.env")])
    if result.exception and not isinstance(result.exception, SystemExit):
        raise result.exception
    return result.exit_code, result.stdout, result.stderr


def ledger(tmp_path: Path) -> list[dict[str, Any]]:
    lines = (tmp_path / "var" / "ledger.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def run_dir(tmp_path: Path, row: dict[str, Any]) -> Path:
    return tmp_path / "var" / "runs" / str(row["run_id"])


def manifest(tmp_path: Path, row: dict[str, Any]) -> dict[str, Any]:
    return json.loads((run_dir(tmp_path, row) / "manifest.json").read_text())
