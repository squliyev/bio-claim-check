"""`llm ping` against the real Foundry deployments (`make live`; never in CI; costs a few tokens).

S09's exit check: each pinged deployment answers through `PingLlmAgent` with a valid structured reply and
honest usage. Only deployment names, codes and token counts are logged, never message text.
"""

import logging
from pathlib import Path

import pytest
from tests.support.events import stepping_clock

from bio_claim_check.app.container import build_llm_clients
from bio_claim_check.app.models import model_catalog
from bio_claim_check.app.settings import load_settings
from bio_claim_check.app.usecases.llm_ping import ping
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.in_memory_event_sink import InMemoryEventSink
from bio_claim_check.engine.events.llm_events import LlmCallFinished
from bio_claim_check.engine.llm.messages import FinishReason

pytestmark = pytest.mark.live
log = logging.getLogger(__name__)

DEPLOYMENTS = ("gpt-6.1-sol", "claude-opus-4-8")


def test_every_adapted_deployment_answers_the_ping(live_env_file: Path) -> None:
    settings = load_settings(live_env_file if live_env_file.is_file() else None)
    if settings.foundry is None:
        pytest.skip("no Foundry settings (BCC_FOUNDRY__BASE_URL / BCC_FOUNDRY__API_KEY in .env)")
    specs = [model_catalog().lookup(name) for name in DEPLOYMENTS]
    sink = InMemoryEventSink()
    with build_llm_clients(settings, specs) as clients:
        results = ping(clients, specs, emitter=EventEmitter(sink, stepping_clock()))
    for result in results:
        log.info(
            "%s pinned=%s served=%s finish=%s usage=%s error=%s",
            result.deployment,
            result.model_version,
            result.served_model,
            result.finish,
            result.usage,
            result.error_code,
        )
    assert [r.error_code for r in results] == [None] * len(specs)
    assert all(r.finish is FinishReason.STOP for r in results)
    assert all(r.usage is not None and r.usage.input_tokens > 0 for r in results)
    finished = [e for e in sink.events if isinstance(e, LlmCallFinished)]
    assert [e.model.deployment for e in finished] == list(DEPLOYMENTS)
