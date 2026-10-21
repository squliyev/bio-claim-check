"""[RING:features/contracts] The evaluation corpus: its spec, its sources and its manifest (ADR 0010).

Why: the corpus slice builds the dev/test split, and traps (S13) and bench (S16) read it. Slices never
import each other, so the shared file format lives here. The models check their own consistency (a
retracted or review source has no candidates, a held-out question is in test), so a hand-edited dataset
file fails on load instead of silently changing a benchmark denominator.
Must not: fetch, sieve or split. That logic lives in `features.corpus`; these are the shapes it writes.

No LLM is involved in this module.
"""

import re
from datetime import date
from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import BeforeValidator, Field, StringConstraints, ValidationError, model_validator

from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.contracts.verdict import NonBlankStr, StrictSpan, ValidatedModel

TRAP_KINDS: Final = (
    OverstatedReason.PRECLINICAL_TO_CLINICAL,
    OverstatedReason.CORRELATION_AS_CAUSATION,
    OverstatedReason.NONSIGNIFICANT_AS_EFFECT,
    OverstatedReason.CERTAINTY_INFLATION,
    OverstatedReason.BACKGROUND_AS_RESULT,
)
"""The overstatement kinds the corpus can supply candidates for (sieve v2)."""

MESH_KINDS: Final = frozenset(
    {OverstatedReason.PRECLINICAL_TO_CLINICAL, OverstatedReason.CORRELATION_AS_CAUSATION}
)
"""Kinds whose sieve rule reads MeSH; a record not yet MeSH-indexed can never prove them."""

REVIEW_TYPES: Final = frozenset({"Review", "Systematic Review", "Meta-Analysis"})
"""Publication types that summarise other work; their abstracts are never trap candidates."""

PROTOCOL_TYPES: Final = frozenset({"Clinical Trial Protocol"})
"""Publication types that describe a planned study; there are no results to overstate."""

NLM_NOTICE: Final = (
    "Courtesy of the U.S. National Library of Medicine. NLM does not endorse this dataset. "
    "Metadata are a dated snapshot (see declared_fetched_on) and are not kept current."
)

QuestionId = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
DomainId = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
Sha256Hex = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _iso_date(value: object) -> object:
    # pydantic's lax date also accepts unix-time integers; a spec date is written as YYYY-MM-DD only
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not _ISO_DATE.match(value):
        raise ValueError("must be a date written as YYYY-MM-DD")
    return value


def _exact_int(value: object) -> object:
    # strict ints still need this for Literal[...]: YAML `true` and `1.0` must not pass as 1
    if type(value) is not int:
        raise ValueError("must be an integer")
    return value


IsoDate = Annotated[date, BeforeValidator(_iso_date)]


class CorpusSplit(StrEnum):
    """Which half of the evaluation corpus a source or question belongs to."""

    DEV = "dev"
    TEST = "test"


class NeverReason(StrEnum):
    """Why a source can never be a trap candidate. It stays in the pool, so retrieval stays realistic."""

    RETRACTED = "retracted"
    REVIEW = "review"
    UNKNOWN_PUBLICATION_TYPES = "unknown_publication_types"
    MESH_NOT_INDEXED = "mesh_not_indexed"
    PROTOCOL = "protocol"


_BLOCKS_ALL_KINDS: Final = frozenset(
    {NeverReason.RETRACTED, NeverReason.REVIEW, NeverReason.UNKNOWN_PUBLICATION_TYPES, NeverReason.PROTOCOL}
)


def never_reasons(
    *, retracted: bool, publication_types: tuple[str, ...], mesh_headings: tuple[str, ...] | None
) -> tuple[NeverReason, ...]:
    """Why a source with this metadata can never be a candidate, in `NeverReason` order; () if it may be.

    The one definition: the sieve applies it and `SourceEntry` re-checks a stored entry against it.
    """
    checks = (
        (NeverReason.RETRACTED, retracted),
        (NeverReason.REVIEW, bool(REVIEW_TYPES.intersection(publication_types))),
        (NeverReason.UNKNOWN_PUBLICATION_TYPES, not publication_types),
        (NeverReason.MESH_NOT_INDEXED, mesh_headings is None),
        (NeverReason.PROTOCOL, bool(PROTOCOL_TYPES.intersection(publication_types))),
    )
    return tuple(reason for reason, applies in checks if applies)


class Domain(ValidatedModel):
    id: DomainId
    held_out: bool = Field(strict=True)
    description: NonBlankStr


class Question(ValidatedModel):
    """A research question: `text` is what an answerer sees, `search` builds its Europe PMC pool."""

    id: QuestionId
    domain: DomainId
    split: CorpusSplit
    text: NonBlankStr
    search: NonBlankStr
    answerable: bool = Field(strict=True)


class CorpusSpec(ValidatedModel):
    """Everything the build reads besides the cache. Committed before any fetch (pre-registration)."""

    schema_version: Annotated[Literal[1], BeforeValidator(_exact_int)]
    sieve_version: Annotated[Literal[2], BeforeValidator(_exact_int)]
    pool_hits: Annotated[Literal[100], BeforeValidator(_exact_int)]
    cutoff: IsoDate
    split_salt: NonBlankStr
    audit_salt: NonBlankStr
    dev_fraction: float = Field(strict=True, gt=0, lt=1)
    audit_n: int = Field(strict=True, ge=1)
    trap_kinds: tuple[OverstatedReason, ...] = Field(min_length=1)
    domains: tuple[Domain, ...] = Field(min_length=1)
    questions: tuple[Question, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        domain_ids = [d.id for d in self.domains]
        if len(set(domain_ids)) != len(domain_ids):
            raise ValueError("domain ids must be unique")
        if sum(d.held_out for d in self.domains) != 1:
            raise ValueError("exactly one domain must be held out")
        question_ids = [q.id for q in self.questions]
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("question ids must be unique")
        held_out = {d.id for d in self.domains if d.held_out}
        for q in self.questions:
            if q.domain not in domain_ids:
                raise ValueError(f"question {q.id}: unknown domain {q.domain!r}")
            if q.domain in held_out and q.split is not CorpusSplit.TEST:
                raise ValueError(f"question {q.id}: a held-out domain's questions must be in test")
        if len(set(self.trap_kinds)) != len(self.trap_kinds):
            raise ValueError("trap_kinds must be unique")
        if unknown := [k.value for k in self.trap_kinds if k not in TRAP_KINDS]:
            raise ValueError(f"trap_kinds not supported by sieve v2: {', '.join(unknown)}")
        return self

    def held_out_domain(self) -> DomainId:
        return next(d.id for d in self.domains if d.held_out)


class Candidate(ValidatedModel):
    """Why the sieve made a source a candidate for one kind. A candidate is not yet confirmed (S07b audit)."""

    kind: OverstatedReason
    rule: Literal[
        "animals_not_humans", "in_vitro", "observational", "null_result", "closing_hedge", "prior_finding"
    ]
    mesh: tuple[str, ...] = ()
    publication_types: tuple[str, ...] = ()
    span: StrictSpan | None = None
    """Offsets of the matching sentence in the cleaned abstract (text rules only)."""


class QuestionRank(ValidatedModel):
    question_id: QuestionId
    rank: int = Field(strict=True, ge=1)


class SourceEntry(ValidatedModel):
    """One source in the corpus: identifiers, metadata and hashes only, never abstract text (ADR 0008)."""

    source_id: SourceId
    year: int | None = Field(strict=True)
    ranks: tuple[QuestionRank, ...] = Field(min_length=1)
    cluster_id: SourceId
    split: CorpusSplit
    retracted: bool = Field(strict=True)
    publication_types: tuple[str, ...]
    mesh_headings: tuple[str, ...] | None
    abstract_sha256: Sha256Hex
    never_because: tuple[NeverReason, ...]
    candidates: tuple[Candidate, ...]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        questions = [r.question_id for r in self.ranks]
        if questions != sorted(set(questions)):
            raise ValueError("ranks must be sorted by question id, one per question")
        expected = never_reasons(
            retracted=self.retracted,
            publication_types=self.publication_types,
            mesh_headings=self.mesh_headings,
        )
        if self.never_because != expected:
            raise ValueError(f"never_because must be {[r.value for r in expected]} for this metadata")
        kinds = [c.kind for c in self.candidates]
        if len(set(kinds)) != len(kinds):
            raise ValueError("at most one candidate per kind")
        if self.candidates and _BLOCKS_ALL_KINDS.intersection(self.never_because):
            raise ValueError("an excluded source has no candidates")
        if NeverReason.MESH_NOT_INDEXED in self.never_because and MESH_KINDS.intersection(kinds):
            raise ValueError("a source without MeSH cannot be a candidate for a MeSH kind")
        return self


class QuestionEntry(Question):
    """A question as built: the exact query sent, a hash of the raw response and of its ranked pool.

    `split_pool_size` counts the pool sources in the question's own split: that filtered pool is the one
    an answerer sees during tuning (dev) or evaluation (test), and "unanswerable" refers to its top 10.
    """

    query: NonBlankStr
    response_sha256: Sha256Hex
    pool_size: int = Field(strict=True, ge=0)
    split_pool_size: int = Field(strict=True, ge=0)
    pool_sha256: Sha256Hex

    @model_validator(mode="after")
    def _pool_sizes(self) -> Self:
        if self.split_pool_size > self.pool_size:
            raise ValueError("split_pool_size cannot exceed pool_size")
        return self


class FileHash(ValidatedModel):
    name: NonBlankStr
    sha256: Sha256Hex


class CandidateCount(ValidatedModel):
    domain: DomainId
    split: CorpusSplit
    kind: OverstatedReason
    n: int = Field(strict=True, ge=0)


class CorpusManifest(ValidatedModel):
    """Written last: it names every data file by hash, so a partial or edited dataset is detectable."""

    schema_version: Annotated[Literal[1], BeforeValidator(_exact_int)]
    tool_version: NonBlankStr
    declared_fetched_on: IsoDate
    spec_sha256: Sha256Hex
    spec_file_sha256: Sha256Hex
    """Of the spec file's bytes, comments included, so an edited pre-registration breaks the seal."""
    notice: NonBlankStr
    files: tuple[FileHash, ...]
    candidate_counts: tuple[CandidateCount, ...]

    @model_validator(mode="after")
    def _credited(self) -> Self:
        if self.notice != NLM_NOTICE:
            raise ValueError("notice must be the NLM credit and snapshot notice (ADR 0008)")
        names = [f.name for f in self.files]
        if names != sorted(set(names)):
            raise ValueError("files must be sorted by name, each once")
        return self


class CorpusSpecError(Exception):
    """A corpus spec could not be loaded. `problems` holds one human-readable line per problem."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = tuple(problems)


def parse_corpus_spec(data: object, source: str) -> CorpusSpec:
    """Validate parsed data (None = an empty file) as a corpus spec; `source` names it in every problem."""
    if data is None:
        raise CorpusSpecError([f"{source}: the file is empty"])
    try:
        return CorpusSpec.model_validate(data)
    except ValidationError as err:
        problems: list[str] = []
        for problem in err.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in problem["loc"]) or "(root)"
            problems.append(f"{source}: {location}: {problem['msg']}")
        raise CorpusSpecError(problems) from None


AuditVerdict = Literal["confirm", "reject"]


class AuditDecision(ValidatedModel):
    """The author's call on one candidate: a rejection must say why."""

    source_id: SourceId
    decision: AuditVerdict
    reason: NonBlankStr | None

    @model_validator(mode="after")
    def _reasoned(self) -> Self:
        if (self.decision == "reject") != (self.reason is not None):
            raise ValueError("a rejection needs a reason, and only a rejection has one")
        return self


class AuditRecord(ValidatedModel):
    """One completed audit of one kind in one split: exactly the first `n` candidates in the public order.

    `corpus_seal` ties it to the sealed dataset; `prompts_sha256` records what was frozen when it was done.
    """

    split: CorpusSplit
    kind: OverstatedReason
    corpus_seal: Sha256Hex
    prompts_sha256: Sha256Hex
    decisions: tuple[AuditDecision, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> Self:
        ids = [d.source_id for d in self.decisions]
        if len(set(ids)) != len(ids):
            raise ValueError("each source is decided once")
        return self
