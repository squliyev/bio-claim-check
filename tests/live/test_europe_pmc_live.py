"""Opt-in checks against the real Europe PMC API (`make live`; never in CI; needs BCC_CONTACT_EMAIL).

They confirm what the offline fixtures assume: the record shape, that the citable-source policy holds on
real results, that every excluded PUB_TYPE spelling matches real records, and that the abstract cleaner
works on real markup. Only counts are logged (`make live` shows them), never publisher text.
"""

import logging
import re
from collections.abc import Generator

import httpx
import pytest

from bio_claim_check.app.container import build_retrieval, user_agent
from bio_claim_check.app.settings import Settings, load_settings
from bio_claim_check.common.text import locate_quote
from bio_claim_check.engine.cache.policy import CacheMode
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.retrieval.citable import EXCLUDED_PUB_TYPES
from bio_claim_check.features.retrieval.europe_pmc_literature_source import SEARCH_URL

pytestmark = pytest.mark.live
log = logging.getLogger(__name__)

SEED_QUERIES = (
    "GLP-1 receptor agonist Alzheimer's disease",
    "GLP-1 receptor agonist Parkinson's disease",
    "metformin cancer",
)
K = 50
LEFTOVER_MARKUP = re.compile(r"</?[a-zA-Z][\w:.-]*[^<>]*>|&[a-zA-Z]+;|&#\d+;")
SENTENCE_BREAK = re.compile(r"(?<=\.) (?=[A-Z])")
GLUED_HEADING = re.compile(r"[a-z](?:Background|Methods|Results|Conclusions?|Objectives?)\b")


@pytest.fixture(scope="module")
def settings() -> Settings:
    return load_settings(None).model_copy(update={"cache_mode": CacheMode.OFF})  # always the real API


@pytest.fixture(scope="module")
def source(settings: Settings) -> Generator[BaseLiteratureSource]:
    with build_retrieval(settings) as live:
        yield live


@pytest.mark.parametrize("query", SEED_QUERIES)
def test_real_results_are_citable_medline_abstracts(source: BaseLiteratureSource, query: str) -> None:
    papers = source.search(query, limit=K)
    assert papers, query
    assert len({p.source_id for p in papers}) == len(papers)
    for paper in papers:
        assert re.fullmatch(r"MED:\d+", paper.source_id), paper.source_id
        assert paper.title.strip()
        assert paper.abstract
    log.info("%r: %d papers, %d retracted", query, len(papers), sum(p.retracted for p in papers))


@pytest.mark.parametrize("pub_type", sorted(EXCLUDED_PUB_TYPES))
def test_every_excluded_pub_type_spelling_is_real(settings: Settings, pub_type: str) -> None:
    params = {"query": f'PUB_TYPE:"{pub_type}" AND SRC:MED', "format": "json", "pageSize": "1"}
    with httpx.Client(timeout=30.0, headers={"User-Agent": user_agent(settings)}) as client:
        response = client.get(SEARCH_URL, params=params)
    response.raise_for_status()
    hits = int(response.json()["hitCount"])
    log.info("PUB_TYPE %r: %d hits", pub_type, hits)
    assert hits > 0, f"no record has PUB_TYPE {pub_type!r}: the spelling is wrong"


def test_the_cleaner_handles_real_markup(source: BaseLiteratureSource) -> None:
    papers = [p for q in SEED_QUERIES for p in source.search(q, limit=40)]
    leftover = sum(bool(LEFTOVER_MARKUP.search(p.abstract)) for p in papers)
    glued = sum(bool(GLUED_HEADING.search(p.abstract)) for p in papers)
    sentences = unlocated = 0
    for paper in papers:
        for sentence in filter(str.strip, SENTENCE_BREAK.split(paper.abstract)):
            sentences += 1
            unlocated += locate_quote(sentence, paper.abstract) is None
    log.info(
        "cleaner: %d abstracts, %d sentences; %d with markup left, %d with a glued heading, "
        "%d sentences not self-located",
        len(papers),
        sentences,
        leftover,
        glued,
        unlocated,
    )
    assert (leftover, glued, unlocated) == (0, 0, 0)
