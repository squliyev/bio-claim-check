"""[RING:features/answer] A scripted answerer for demos and tests.

Why: the walking skeleton (S05) needs answers without an LLM. Each mode returns a fixed, fictional
script; over-eager deliberately overstates, fabricates and invents a citation, so every failure path
of the pipeline shows up in the demo.
Must not: be wired into a live run. It ignores the papers it is given: if retrieval returned fewer
papers than the script cites, those cites are reported as not retrieved, which is the honest outcome.

No LLM is involved in this module.
"""

from collections.abc import Mapping

from bio_claim_check.features.contracts.answer import Answer
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.verdict import Claim

STRICT_SCRIPT: tuple[Claim, ...] = (
    Claim(id="s1", text="OS-912 reduced amyloid plaque load in APP/PS1 mice.", cites=("FAKE:1",)),
    Claim(
        id="s2",
        text="OS-912 use was associated with a lower incidence of dementia in adults.",
        cites=("FAKE:3", "FAKE:4"),
    ),
    Claim(
        id="s3",
        text="HX-15 did not significantly change cognitive scores in a phase 2 trial.",
        cites=("FAKE:2",),
    ),
)

OVER_EAGER_SCRIPT: tuple[Claim, ...] = (
    Claim(id="o1", text="OS-912 slows cognitive decline in patients.", cites=("FAKE:1",)),
    Claim(id="o2", text="OS-912 prevents dementia.", cites=("FAKE:3",)),
    Claim(id="o3", text="HX-15 significantly improved cognitive scores.", cites=("FAKE:2",)),
    Claim(id="o4", text="OS-912 cut plaque load by more than a third in mice.", cites=("FAKE:1",)),
    Claim(id="o5", text="OS-912 is approved for the treatment of dementia.", cites=("FAKE:99",)),
    Claim(id="o6", text="Plaque-targeting compounds work in humans.", cites=("FAKE:4",)),
)

SCRIPTS: Mapping[AnswerMode, tuple[Claim, ...]] = {
    AnswerMode.STRICT: STRICT_SCRIPT,
    AnswerMode.OVER_EAGER: OVER_EAGER_SCRIPT,
}


class ScriptedAnswerer:
    """Answers any question with the fixed script for the requested mode."""

    def __init__(self, scripts: Mapping[AnswerMode, tuple[Claim, ...]] = SCRIPTS) -> None:
        self._scripts = scripts

    def answer(self, question: str, papers: tuple[Paper, ...], mode: AnswerMode) -> Answer:
        del papers  # scripted: see the module docstring
        return Answer(question=question, mode=mode, claims=self._scripts[mode])
