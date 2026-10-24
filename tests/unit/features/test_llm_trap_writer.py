"""The LLM trap writer sees one kind and one paper, and maps output failures exactly like the verifier."""

import json

import pytest
from tests.support.llm import response, spec

from bio_claim_check.app.container import default_rulepack
from bio_claim_check.engine.llm.errors import LlmFailureKind
from bio_claim_check.engine.llm.scripted_llm_client import ScriptedLlmClient
from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.retrieval.in_memory_literature_source import FAKE_CORPUS
from bio_claim_check.features.traps.llm_trap_writer import SOURCE_FAILURE, LlmTrapWriter
from bio_claim_check.features.traps.models import TrapDraft
from bio_claim_check.features.traps.trap_llm_agent import TrapLlmAgent
from bio_claim_check.features.traps.trap_prompts import TRAP_PROMPT
from bio_claim_check.features.verify.llm_verifier import PAIR_FAILURE

PAPER = FAKE_CORPUS[0]
KIND = OverstatedReason.PRECLINICAL_TO_CLINICAL
RULE = next(r for r in default_rulepack().rules if r.reason is KIND)


def test_the_failure_mapping_is_the_verifiers() -> None:
    assert SOURCE_FAILURE == PAIR_FAILURE
    assert set(SOURCE_FAILURE) == set(LlmFailureKind)


def test_the_writer_sees_the_kind_definition_and_the_paper_only() -> None:
    client = ScriptedLlmClient([response(TrapDraft(parent="A held.", trap="A holds.").model_dump_json())])
    LlmTrapWriter(TrapLlmAgent(client, spec())).draft(KIND, RULE, PAPER)
    (request,) = client.requests
    user = request.messages[-1].content
    assert json.loads(user.split("Overstatement (JSON):\n")[1].split("\n\n")[0]) == {
        "reason": KIND.value,
        "definition": RULE.definition,
    }
    assert PAPER.source_id not in user
    for example in RULE.examples:
        assert example.claim not in user
        assert example.claim not in request.messages[0].content


@pytest.mark.parametrize("kind", [k for k in OverstatedReason if k is not OverstatedReason.OTHER])
def test_the_prompt_names_no_kind_and_asks_for_no_rationale(kind: OverstatedReason) -> None:
    assert kind.value not in TRAP_PROMPT.system
    assert "reason" not in TrapDraft.model_fields
