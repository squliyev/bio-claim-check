"""No prompt or rule-pack text names a benchmark topic (I75, ADR 0021).

The few-shot examples teach each rule on fictional compounds. If they also sat on our questions' topics
(a drug, disease or model the search targets), they could inflate verdicts on exactly those questions.
The topic terms are the search terms of every question's query (both splits: only the queries are read,
never an abstract). A term that is generic study vocabulary, which the rules must use, is listed in
`GENERIC` with its reason; anything else that appears is a failure naming the term and the questions.
"""

import json
import re

import pytest

from bio_claim_check.app.container import default_rulepack
from bio_claim_check.engine.prompts.prompt_template import PromptTemplate
from bio_claim_check.features.verify.verify_prompts import render_rules
from tests.support.guards import import_package
from tests.support.paths import ROOT

pytestmark = pytest.mark.arch

GENERIC: dict[str, str] = {
    "case-control": "study design, a rule cue",
    "cohort": "study design, a rule cue",
    "registry": "study design, a rule cue",
    "trial": "study design",
    "in vitro": "model system, a rule cue",
    "mice": "model organism, a rule cue",
    "rats": "model organism, a rule cue",
    "concentration*": "exposure vocabulary, a rule cue",
    "sex": "population vocabulary, a rule cue",
    "survival": "a generic end point (the subgroup example)",
    "liver": "an organ, not a topic (the dose example's rat liver injury)",
    "statin*": "the wildcard also matches 'stating'; the drug class is checked as 'statin' and 'statins'",
}
"""Query terms allowed in prompt text, each with why it is not a topic."""

_DATE = re.compile(r"FIRST_PDATE:\[[^\]]*\]")
_FIELD = re.compile(r"\b[A-Z_]+:")
_PHRASE = re.compile(r'"([^"]+)"')


def _query_terms(query: str) -> set[str]:
    q = _FIELD.sub("", _DATE.sub("", query))
    terms = _PHRASE.findall(q)
    terms += [w for w in re.findall(r"[A-Za-z0-9*'-]+", _PHRASE.sub(" ", q)) if w not in ("AND", "OR", "NOT")]
    return {t.lower() for t in terms}


def topic_terms() -> dict[str, list[str]]:
    """Each query term, with the ids of the questions that search for it."""
    terms: dict[str, list[str]] = {}
    for line in (ROOT / "datasets" / "questions.jsonl").read_text().splitlines():
        question = json.loads(line)
        for term in _query_terms(question["query"]):
            terms.setdefault(term, []).append(question["id"])
    return terms


def feature_prompts() -> dict[str, PromptTemplate]:
    """Every module-level prompt in a feature slice, by name, found at runtime (so a new one is covered)."""
    return {
        value.name: value
        for module in import_package("bio_claim_check.features").values()
        for value in vars(module).values()
        if isinstance(value, PromptTemplate)
    }


def _prompt_text() -> str:
    prompts = tuple(feature_prompts().values())
    return " ".join([p.system for p in prompts] + [render_rules(default_rulepack())]).lower()


def _named(term: str, text: str) -> bool:
    stem = re.escape(term.rstrip("*"))
    return re.search(rf"\b{stem}" + (r"\w*" if term.endswith("*") else r"\b"), text) is not None


def test_no_prompt_or_rule_text_names_a_benchmark_topic() -> None:
    text = _prompt_text()
    named = [f"{t} {ids}" for t, ids in sorted(topic_terms().items()) if t not in GENERIC and _named(t, text)]
    assert named == []


def test_every_feature_prompt_is_covered() -> None:
    assert {"verify", "answer_strict", "answer_over_eager", "trap"} <= set(feature_prompts())


def test_the_topic_terms_are_read_and_every_generic_term_is_one() -> None:
    terms = topic_terms()
    assert {"metformin", "alzheimer*", "colorectal", "diabet*"} <= set(terms)
    assert set(GENERIC) <= set(terms)


def test_a_planted_topic_in_prompt_text_is_caught() -> None:
    text = _prompt_text() + " in people with alzheimer's disease taking metformin"
    assert _named("alzheimer*", text)
    assert _named("metformin", text)
    assert not _named("statin", "the abstract states")
