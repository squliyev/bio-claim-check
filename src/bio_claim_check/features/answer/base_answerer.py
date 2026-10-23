"""[RING:features/answer] The port the answer slice owns: something that answers from given papers.

Why: the use case depends on this base; implementations subclass it and sit beside it, named by
backend (ADR 0007): `scripted_answerer` for the fake run and `llm_answerer` (S10) for live answers.
Replaced the structural `ports.Answerer` Protocol in S05b.
Must not: hold any implementation, or import one.

No LLM is involved in this module.
"""

from abc import ABC, abstractmethod

from bio_claim_check.features.contracts.answer import Answer
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.contracts.paper import Paper


class BaseAnswerer(ABC):
    """Answers a question using only the given papers."""

    @abstractmethod
    def answer(self, question: str, papers: tuple[Paper, ...], mode: AnswerMode) -> Answer:
        """Answer `question` from `papers` only.

        Returns:
            An answer that echoes `question` and `mode`; every claim cites by source id.
        """
