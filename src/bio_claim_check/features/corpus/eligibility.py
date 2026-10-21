"""[RING:features/corpus] Sieve v1: which abstracts may later carry a planted overstatement (ADR 0010).

Why: a trap of kind K is only fair if its source abstract can be overstated in way K (an animal-only
finding for `preclinical_to_clinical`, a null result for `nonsignificant_as_effect`). The rules are fixed
before any data is seen (pre-registration) and read only stored metadata and the cleaned abstract, so
the same paper always gets the same answer. Missing metadata fails closed: an unindexed record cannot
prove "no Humans tag", and unknown publication types cannot prove "not a review".
Must not: call an LLM, fetch, or widen a rule after the pool is seen (that is sieve v2 and a new ADR).

No LLM is involved in this module.
"""

import re
from collections.abc import Sequence
from typing import Final

from bio_claim_check.common.text import CleanedText, Span
from bio_claim_check.features.contracts.corpus import (
    MESH_KINDS,
    REVIEW_TYPES,
    TRAP_KINDS,
    Candidate,
    NeverReason,
)
from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.contracts.paper import Paper

SIEVE_VERSION: Final = 1

IN_VITRO_MESH: Final = frozenset({"Cell Line", "Cell Line, Tumor", "Cells, Cultured", "In Vitro Techniques"})
OBSERVATIONAL_MESH: Final = frozenset(
    {
        "Cohort Studies",
        "Prospective Studies",
        "Retrospective Studies",
        "Case-Control Studies",
        "Cross-Sectional Studies",
    }
)
CLINICAL_DESIGN_MESH: Final = OBSERVATIONAL_MESH | {"Clinical Trials as Topic"}
"""Any human study design blocks the in-vitro rule (fail closed: such a paper is not cells-only)."""
TRIAL_TYPES: Final = frozenset({"Randomized Controlled Trial"})
"""Plus every type starting with "Clinical Trial" (Clinical Trial, Phase I … IV, Protocol)."""
OBSERVATIONAL_TYPE: Final = "Observational Study"

NULL_RESULT: Final = (
    re.compile(r"\bnot? (?:statistically )?significant(?:ly)?\b", re.IGNORECASE),
    re.compile(r"\bdid not (?:differ|improve|reduce|change|increase|decrease)", re.IGNORECASE),
    re.compile(r"\bp\s*(?:>|=|≥)\s*0?\.(?:0[5-9]|[1-9])\d*(?!\.?\d)", re.IGNORECASE),  # any p ≥ 0.05
)
CLOSING_HEDGE: Final = re.compile(
    r"\b(?:may|might|could|suggest(?:s|ed)?|potential(?:ly)?|possibl[ey]|warrant(?:s|ed)?"
    r"|further (?:studies|research))\b",
    re.IGNORECASE,
)

_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])")
_NO_SPLIT_AFTER = re.compile(
    r"(?:\be\.g\.|\bi\.e\.|\bvs\.|\bal\.|\bFigs?\.|\bapprox\.|\bca\.)$", re.IGNORECASE
)


def sentences(text: CleanedText) -> tuple[Span, ...]:
    """Conservative sentence spans: a boundary is [.!?] + space + capital/digit/bracket, never after an
    abbreviation such as e.g., i.e., vs., et al. or Fig. Decimals never split (no space after the dot)."""
    spans: list[Span] = []
    start = 0
    for boundary in _BOUNDARY.finditer(text):
        if _NO_SPLIT_AFTER.search(text, 0, boundary.start()):
            continue
        if boundary.start() > start:
            spans.append(Span(start, boundary.start()))
        start = boundary.end()
    end = len(text.rstrip())
    if end > start:
        spans.append(Span(start, end))
    return tuple(spans)


def _is_trial(types: Sequence[str]) -> bool:
    return any(t in TRIAL_TYPES or t.startswith("Clinical Trial") for t in types)


def exclusions(paper: Paper) -> tuple[NeverReason, ...]:
    """Why `paper` can never be a candidate, in `NeverReason` order; () if it may be one."""
    checks = (
        (NeverReason.RETRACTED, paper.retracted),
        (NeverReason.REVIEW, bool(REVIEW_TYPES.intersection(paper.publication_types))),
        (NeverReason.UNKNOWN_PUBLICATION_TYPES, not paper.publication_types),
        (NeverReason.MESH_NOT_INDEXED, paper.mesh_headings is None),
    )
    return tuple(reason for reason, applies in checks if applies)


def _preclinical(mesh: frozenset[str], types: Sequence[str]) -> Candidate | None:
    kind = OverstatedReason.PRECLINICAL_TO_CLINICAL
    if "Animals" in mesh and "Humans" not in mesh:
        return Candidate(kind=kind, rule="animals_not_humans", mesh=("Animals",))
    in_vitro = sorted(IN_VITRO_MESH & mesh)
    clinical = CLINICAL_DESIGN_MESH & mesh or _is_trial(types) or OBSERVATIONAL_TYPE in types
    if in_vitro and not clinical:
        return Candidate(kind=kind, rule="in_vitro", mesh=tuple(in_vitro))
    return None


def _observational(mesh: frozenset[str], types: Sequence[str]) -> Candidate | None:
    if _is_trial(types):
        return None
    found = sorted(OBSERVATIONAL_MESH & mesh)
    observational_type = (OBSERVATIONAL_TYPE,) if OBSERVATIONAL_TYPE in types else ()
    if not found and not observational_type:
        return None
    return Candidate(
        kind=OverstatedReason.CORRELATION_AS_CAUSATION,
        rule="observational",
        mesh=tuple(found),
        publication_types=observational_type,
    )


def _null_result(text: CleanedText, sentences: Sequence[Span]) -> Candidate | None:
    for span in sentences:
        if any(p.search(span.of(text)) for p in NULL_RESULT):
            return Candidate(kind=OverstatedReason.NONSIGNIFICANT_AS_EFFECT, rule="null_result", span=span)
    return None


def _closing_hedge(text: CleanedText, sentences: Sequence[Span]) -> Candidate | None:
    for span in sentences[-2:]:
        if CLOSING_HEDGE.search(span.of(text)):
            return Candidate(kind=OverstatedReason.CERTAINTY_INFLATION, rule="closing_hedge", span=span)
    return None


def candidates(paper: Paper, kinds: Sequence[OverstatedReason]) -> tuple[Candidate, ...]:
    """The sieve-v1 candidates of `paper` for `kinds`, in `kinds` order (ADR 0010 §sieve)."""
    if unknown := [k for k in kinds if k not in TRAP_KINDS]:
        raise ValueError(f"sieve v1 has no rule for {', '.join(k.value for k in unknown)}")
    excluded = exclusions(paper)
    if set(excluded) - {NeverReason.MESH_NOT_INDEXED}:
        return ()
    mesh = frozenset(paper.mesh_headings or ())
    types = paper.publication_types
    text = paper.abstract
    spans = sentences(text)
    found: list[Candidate] = []
    for kind in kinds:
        if kind in MESH_KINDS and paper.mesh_headings is None:
            continue
        match kind:
            case OverstatedReason.PRECLINICAL_TO_CLINICAL:
                hit = _preclinical(mesh, types)
            case OverstatedReason.CORRELATION_AS_CAUSATION:
                hit = _observational(mesh, types)
            case OverstatedReason.NONSIGNIFICANT_AS_EFFECT:
                hit = _null_result(text, spans)
            case OverstatedReason.CERTAINTY_INFLATION:
                hit = _closing_hedge(text, spans)
            case _:  # pragma: no cover - rejected above; kept so a new TRAP_KINDS entry fails loudly
                raise AssertionError(kind)
        if hit is not None:
            found.append(hit)
    return tuple(found)
