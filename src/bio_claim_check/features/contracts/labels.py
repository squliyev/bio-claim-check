"""[RING:features/contracts] The closed vocabularies behind every verdict (ADR 0006).

Why: two axes are kept apart on purpose. `Label` is what the LLM judged; `EvidenceStatus` and
`NegationCheck` are what code verified. `Disposition` is derived from all three and is never produced
by an LLM. The string values are part of the pre-registered protocol and are frozen by committed
schema snapshots; renaming one is a protocol change, not a refactor.
Must not: hold behaviour; the rules that combine these live in `verdict.py`.

No LLM is involved in this module.
"""

from enum import StrEnum


class Label(StrEnum):
    """The verifier's semantic judgement of one claim against one cited source."""

    SUPPORTED = "supported"
    OVERSTATED = "overstated"
    CONTRADICTED = "contradicted"
    NOT_IN_SOURCE = "not_in_source"


class EvidenceStatus(StrEnum):
    """What code found when it looked for the quoted evidence in the cleaned abstract."""

    LOCATED = "located"
    NEAR = "near"
    ABSENT = "absent"
    NOT_REQUIRED = "not_required"


class NegationCheck(StrEnum):
    """Whether a located quote sits under a negation ("no significant reduction"). Detector arrives in S10."""

    NOT_RUN = "not_run"
    CLEAR = "clear"
    NEGATED = "negated"


class Disposition(StrEnum):
    """What a reader should do with a (claim, source) pair. PASSED means every check passed, not "true"."""

    PASSED = "passed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    FLAGGED = "flagged"


class AnswerMode(StrEnum):
    """How the answering agent behaves. Over-eager exists to produce overstatements to catch."""

    STRICT = "strict"
    OVER_EAGER = "over_eager"


class FailureKind(StrEnum):
    """Why the verifier produced no usable output for a pair. Counted, never dropped."""

    STRUCTURED_OUTPUT = "structured_output"
    CONTENT_FILTERED = "content_filtered"
    PROVIDER_ERROR = "provider_error"


class OverstatedReason(StrEnum):
    """How a claim goes beyond its source. Mapped to the spin literature in ADR 0006."""

    PRECLINICAL_TO_CLINICAL = "preclinical_to_clinical"
    BACKGROUND_AS_RESULT = "background_as_result"
    SURROGATE_AS_CLINICAL = "surrogate_as_clinical"
    CORRELATION_AS_CAUSATION = "correlation_as_causation"
    SELECTIVE_ANALYSIS_AS_MAIN = "selective_analysis_as_main"
    NONSIGNIFICANT_AS_EFFECT = "nonsignificant_as_effect"
    DOSE_OR_EXPOSURE_EXTRAPOLATION = "dose_or_exposure_extrapolation"
    POPULATION_EXTRAPOLATION = "population_extrapolation"
    CERTAINTY_INFLATION = "certainty_inflation"
    OTHER = "other"
