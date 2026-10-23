"""I69: the verifier request carries the claim, the title, the cleaned abstract and the rules, nothing else.

`BaseVerifier.verify` takes one claim, one paper and the rule pack, so the question, other claims and other
papers cannot reach it by construction. Sentinels are planted in every field of those three inputs that
the verifier must not see (ids, DOI, MeSH, publication types, licence, raw markup, rule references and
authors); the test reads the bytes the client was actually sent.
"""

import pytest
from tests.support.llm import response, spec

from bio_claim_check.app.container import default_rulepack
from bio_claim_check.engine.llm.scripted_llm_client import ScriptedLlmClient
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.rulepack import RulePack
from bio_claim_check.features.contracts.verdict import Claim
from bio_claim_check.features.verify.llm_verifier import LlmVerifier
from bio_claim_check.features.verify.verify_llm_agent import VerifyLlmAgent

pytestmark = pytest.mark.unit

REPLY = '{"label": "not_in_source", "overstated_reason": null, "evidence": null, "reason": "Absent."}'


def _rules_with_reference(sentinel: str) -> RulePack:
    pack = default_rulepack()
    first, *rest = pack.rules
    first = first.model_validate({**first.model_dump(), "references": [sentinel]})
    return pack.model_validate({**pack.model_dump(), "rules": [first, *rest], "authors": ["AUTHOR_SENTINEL"]})


def test_only_the_pair_reaches_the_request() -> None:
    paper = Paper(
        source_id="MED:11111111",
        title="TITLE_SENTINEL",
        year=2020,
        raw_abstract='ABSTRACT_SENTINEL <i class="MARKUP_SENTINEL">plaque</i> fell.',
        doi="10.1/DOI_SENTINEL",
        mesh_headings=("MESH_SENTINEL",),
        publication_types=("PUBTYPE_SENTINEL",),
        license="LICENSE_SENTINEL",
    )
    claim = Claim(id="CLAIMID_SENTINEL", text="CLAIM_SENTINEL plaque fell.", cites=(paper.source_id,))
    client = ScriptedLlmClient([response(REPLY)])
    LlmVerifier(VerifyLlmAgent(client, spec())).verify(claim, paper, _rules_with_reference("REF_SENTINEL"))
    (request,) = client.requests
    sent = request.model_dump_json()
    for kept in ("CLAIM_SENTINEL", "TITLE_SENTINEL", "ABSTRACT_SENTINEL"):
        assert kept in sent
    for leaked in (
        "CLAIMID_SENTINEL",
        "11111111",
        "DOI_SENTINEL",
        "MESH_SENTINEL",
        "PUBTYPE_SENTINEL",
        "LICENSE_SENTINEL",
        "MARKUP_SENTINEL",
        "REF_SENTINEL",
        "AUTHOR_SENTINEL",
    ):
        assert leaked not in sent
