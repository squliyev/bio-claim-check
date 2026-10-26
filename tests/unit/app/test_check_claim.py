import pytest
from tests.support.checks import CLAIM_TEXT, PMID, SOURCE_ID, VERIFIER, live_check_ports
from tests.support.events import stepping_clock

from bio_claim_check.app.container import build_fake_check_ports, fake_check_claims
from bio_claim_check.app.usecases.check_claim import (
    LIVE_CLAIM_ID,
    MAX_CLAIM_CHARS,
    CheckInputError,
    check_claim,
    live_claim,
    parse_pmid,
    validate_claim_text,
)
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.events.in_memory_event_sink import InMemoryEventSink
from bio_claim_check.engine.events.stage_events import StageFinished
from bio_claim_check.features.contracts.labels import Disposition, OverstatedReason
from bio_claim_check.features.contracts.verdict import Claim
from bio_claim_check.features.report.models import (
    CHECK_FAKE_NOTICE,
    CHECK_LIVE_NOTICE,
    FailurePair,
    VerdictPair,
)
from bio_claim_check.features.retrieval.errors import PaperNotFoundError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12345678", "MED:12345678"),
        ("  12345678\n", "MED:12345678"),
        ("PMID:12345678", "MED:12345678"),
        ("pmid: 12345678", "MED:12345678"),
        ("PMID 12345678", "MED:12345678"),
        ("MED:1", "MED:1"),
        ("999999999", "MED:999999999"),
    ],
)
def test_a_pmid_as_typed_becomes_a_med_id(raw: str, expected: str) -> None:
    assert parse_pmid(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "0",
        "012345678",
        "1234567890",
        "12345678 OR 1",
        "12345678)",
        "PMC1234567",
        "FAKE:1",
        "MED:",
        "doi:10.1/x",
        "\uff11\uff12\uff13\uff14",  # full-width digits are not ASCII digits
        "12 345",
    ],
)
def test_anything_else_is_refused_before_a_request(raw: str) -> None:
    with pytest.raises(CheckInputError, match="not a PMID"):
        parse_pmid(raw)


def test_claim_text_is_stripped_and_bounded() -> None:
    assert validate_claim_text("  a claim \n") == "a claim"
    assert validate_claim_text("x" * MAX_CLAIM_CHARS) == "x" * MAX_CLAIM_CHARS
    with pytest.raises(CheckInputError, match="blank"):
        validate_claim_text(" \t\n")
    with pytest.raises(CheckInputError, match=f"at most {MAX_CLAIM_CHARS}"):
        validate_claim_text("x" * (MAX_CLAIM_CHARS + 1))
    with pytest.raises(CheckInputError, match="control characters"):
        validate_claim_text("a\x00claim")


def test_a_live_claim_has_one_id_and_cites_the_named_paper() -> None:
    claim = live_claim(f" {CLAIM_TEXT} ", f"PMID: {PMID}")
    assert claim == Claim(id=LIVE_CLAIM_ID, text=CLAIM_TEXT, cites=(SOURCE_ID,))


def test_a_live_check_flags_the_overstated_claim_with_its_evidence() -> None:
    sink = InMemoryEventSink()
    result = check_claim(live_check_ports(EventEmitter(sink, stepping_clock())), live_claim(CLAIM_TEXT, PMID))
    assert result.provenance == "live"
    assert result.notice == CHECK_LIVE_NOTICE
    assert result.verifier == VERIFIER
    assert result.paper.source_id == SOURCE_ID
    assert result.claim.disposition is Disposition.FLAGGED
    pair = result.claim.pairs[0]
    assert isinstance(pair, VerdictPair)
    assert pair.verdict.overstated_reason is OverstatedReason.PRECLINICAL_TO_CLINICAL
    assert pair.verdict.evidence_span is not None
    stages = [e.stage for e in sink.events if isinstance(e, StageFinished)]
    assert stages == ["retrieve", "verify"]


def test_every_fictional_example_checks_offline() -> None:
    examples = fake_check_claims()
    assert {c.id for c in examples} == {"s1", "s3", "o1", "o2", "o3", "o4", "o6"}
    for claim in examples:
        result = check_claim(build_fake_check_ports(), claim)
        assert result.provenance == "fake"
        assert result.notice == CHECK_FAKE_NOTICE
        assert result.verifier is None
        assert result.paper.source_id == claim.cites[0]
    failed = check_claim(build_fake_check_ports(), next(c for c in examples if c.id == "o6"))
    assert isinstance(failed.claim.pairs[0], FailurePair)


def test_a_check_cites_exactly_one_paper() -> None:
    claim = Claim(id="c1", text="Two papers.", cites=("FAKE:1", "FAKE:2"))
    with pytest.raises(CheckInputError, match="exactly one paper"):
        check_claim(build_fake_check_ports(), claim)


def test_a_bad_claim_is_refused_before_the_fetch() -> None:
    claim = Claim(id="c1", text="x" * (MAX_CLAIM_CHARS + 1), cites=("FAKE:404",))
    with pytest.raises(CheckInputError, match="at most"):
        check_claim(build_fake_check_ports(), claim)


def test_a_paper_that_is_not_there_is_a_typed_failure() -> None:
    with pytest.raises(PaperNotFoundError):
        check_claim(build_fake_check_ports(), Claim(id="c1", text="A claim.", cites=("FAKE:404",)))
