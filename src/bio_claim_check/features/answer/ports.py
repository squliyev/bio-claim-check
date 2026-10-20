"""[RING:features/answer] The port the answer slice owns: something that answers from given papers.

Why: the use case depends on this interface; a scripted fake implements it now (S05), the LLM answerer
in S10.
Must not: hold any implementation.
"""

from typing import Protocol

from bio_claim_check.features.contracts.answer import Answer
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.contracts.paper import Paper


class Answerer(Protocol):
    """Answers a question using only the given papers."""

    def answer(self, question: str, papers: tuple[Paper, ...], mode: AnswerMode) -> Answer:
        """An answer that echoes `question` and `mode`; every claim cites by source id."""
        raise NotImplementedError
