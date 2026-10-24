"""The validity gate: no long claims, no copying the abstract, no echo of a rule-pack example (I77)."""

from bio_claim_check.app.container import default_rulepack
from bio_claim_check.common.text import CleanedText
from bio_claim_check.features.traps.models import MAX_CLAIM_WORDS
from bio_claim_check.features.traps.validity import (
    claim_problems,
    contamination,
    example_texts,
    pair_problems,
    shares_run,
    words,
)

PACK = default_rulepack()
ABSTRACT = CleanedText("In aged mice, the compound reduced amyloid plaque load by a third over twelve weeks.")


def test_words_ignore_case_and_punctuation() -> None:
    assert words("Plaque, LOAD; fell.") == ["plaque", "load", "fell"]


def test_a_paraphrase_passes() -> None:
    assert claim_problems("The compound cut plaque in old mice.", ABSTRACT, PACK) == []


def test_a_copied_run_and_a_long_claim_are_excluded() -> None:
    copied = "Notably the compound reduced amyloid plaque load by a third over time."
    assert claim_problems(copied, ABSTRACT, PACK) == ["copies 8 consecutive words of the abstract"]
    long = " ".join(["word"] * (MAX_CLAIM_WORDS + 1))
    assert claim_problems(long, ABSTRACT, PACK) == [f"longer than {MAX_CLAIM_WORDS} words"]


def test_echoing_any_rule_pack_example_is_contamination() -> None:
    texts = example_texts(PACK)
    assert texts
    for text in texts:
        echo = " ".join(words(text)[:6])
        if len(words(text)) >= 6:
            assert contamination(f"So {echo} today.", PACK)
    assert contamination("Nothing here resembles any example at all.", PACK) == []


def test_shares_run_needs_the_full_run() -> None:
    assert not shares_run("a b c", ["a b c"], 4)
    assert shares_run("x a b c d", ["a b c d y"], 4)


def test_a_trap_must_differ_from_its_parent() -> None:
    assert pair_problems("X helps mice.", "x helps  mice") == ["the trap repeats its parent"]
    assert pair_problems("X helps mice.", "X helps people.") == []
