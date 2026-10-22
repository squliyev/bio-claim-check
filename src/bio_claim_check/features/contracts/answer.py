"""[RING:features/contracts] An agent's answer: the claims it makes and the sources each one cites.

Why: the checks, the verifier and the report all read an answer, so its shape is shared. An empty
claim list is a valid answer: the agent abstained ("cannot determine from these abstracts").
Must not: hold prose that is not split into claims; anything a reader is asked to trust is a claim.

No LLM is involved in this module.
"""

from typing import Self

from pydantic import model_validator

from bio_claim_check.common.models import NonBlankStr, ValidatedModel
from bio_claim_check.features.contracts.labels import AnswerMode
from bio_claim_check.features.contracts.verdict import Claim


class Answer(ValidatedModel):
    """The answer to one question in one mode. Claim ids are unique; no claims means it abstained."""

    question: NonBlankStr
    mode: AnswerMode
    claims: tuple[Claim, ...]

    @model_validator(mode="after")
    def _claim_ids_are_unique(self) -> Self:
        ids = [claim.id for claim in self.claims]
        if len(set(ids)) != len(ids):
            raise ValueError("claim ids must be unique within an answer")
        return self
