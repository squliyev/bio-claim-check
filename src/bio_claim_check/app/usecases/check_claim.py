"""[RING:app/usecases] Check one claim a person wrote against one paper they named (command `check`).

Why: the run flow checks claims an answerer wrote, so whether a demo shows an overstated claim depends on
what the answerer writes. A single check lets a person put a claim to the verifier directly (S17a,
ADR 0025): fetch → verify → `ClaimCheck`. It is the same verifier, rule pack and evidence check as a run;
only where the claim comes from differs. The PMID a person types is parsed by one strict function before
anything else, because it ends up inside a database query. A paper in the sealed test split is refused
before it is fetched (I84, H1): checking it would expose held-out data to the verifier and the reader.
Must not: do I/O (the caller records the artifact), retry, re-judge or edit the verifier's outcome, or
import the container, the driving adapters or infrastructure.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from bio_claim_check.common.errors import BccError
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.stage_events import stage
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.rulepack import RulePack
from bio_claim_check.features.contracts.verdict import Claim
from bio_claim_check.features.report.models import ClaimCheck, ClaimReport, ModelUse, Provenance, pair_report
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.verify.base_verifier import BaseVerifier

MAX_CLAIM_CHARS: Final = 1000
"""One claim, not a paragraph: the verifier judges one atomic statement."""
LIVE_CLAIM_ID: Final = "c1"
_PMID: Final = re.compile(r"(?:PMID|MED)?:?\s*([1-9][0-9]{0,8})", re.IGNORECASE)


class CheckInputError(BccError):
    """The claim is blank, too long or has control characters, or the PMID is not a PMID."""

    code = "check.input"


class HeldOutSourceError(BccError):
    """The paper is in the sealed test split; it is held out, so it is never fetched, answered or verified."""

    code = "check.test_split"

    def __init__(self, source_ids: Iterable[SourceId]) -> None:
        ids = ", ".join(sorted(source_ids))
        super().__init__(f"{ids} is in the sealed test split; held-out papers cannot be checked")
        self.source_ids = tuple(sorted(source_ids))


@dataclass(frozen=True, slots=True)
class CheckPorts:
    """Everything one check needs, chosen by the composition root. `verifier_model` is None when fake.
    `closed_ids` are the sealed test-split ids a check refuses; required, so no builder forgets it (I84)."""

    literature: BaseLiteratureSource
    verifier: BaseVerifier
    rules: RulePack
    provenance: Provenance
    rules_sha256: str
    closed_ids: frozenset[SourceId]
    verifier_model: ModelUse | None = None
    emitter: EventEmitter | None = None


def parse_pmid(raw: str) -> SourceId:
    """`MED:<digits>` for a PMID as a person types it (`12345678`, `PMID: 12345678`, `MED:12345678`)."""
    match = _PMID.fullmatch(raw.strip())
    if match is None:
        raise CheckInputError(f"not a PMID: {raw.strip()[:40]!r} (expected 1 to 9 digits, no leading zero)")
    return f"MED:{match.group(1)}"


def validate_claim_text(text: str) -> str:
    """The claim with outer whitespace removed; `CheckInputError` if no verifier should see it."""
    claim = text.strip()
    if not claim:
        raise CheckInputError("the claim must not be blank")
    if len(claim) > MAX_CLAIM_CHARS:
        raise CheckInputError(f"the claim is {len(claim)} characters; at most {MAX_CLAIM_CHARS}")
    if any(unicodedata.category(c) == "Cc" for c in claim):
        raise CheckInputError("the claim must not contain control characters")
    return claim


def live_claim(text: str, raw_pmid: str) -> Claim:
    """The claim a person typed, on the paper they named: id `c1`, both inputs checked before any fetch."""
    return Claim(id=LIVE_CLAIM_ID, text=validate_claim_text(text), cites=(parse_pmid(raw_pmid),))


def check_claim(c: CheckPorts, claim: Claim) -> ClaimCheck:
    """Fetch the one paper `claim` cites, verify the pair, and build the checked artifact."""
    validate_claim_text(claim.text)
    if len(claim.cites) != 1:
        raise CheckInputError(f"a check cites exactly one paper, got {len(claim.cites)}")
    if claim.cites[0] in c.closed_ids:
        raise HeldOutSourceError(claim.cites)
    with stage(c.emitter, "retrieve"):
        paper = c.literature.fetch(claim.cites[0])
    if paper.source_id != claim.cites[0]:
        raise ValueError(f"literature source returned {paper.source_id} for {claim.cites[0]}")
    with stage(c.emitter, "verify"):
        outcome = c.verifier.verify(claim, paper, c.rules)
    return ClaimCheck(
        provenance=c.provenance,
        claim=ClaimReport(claim=claim, pairs=(pair_report(outcome),)),
        paper=paper,
        verifier=c.verifier_model,
    )
