"""[RING:app/ui] What the UI page asks for, as plain data: the list of recorded runs and the About tables.

Why: `page.py` must only render (I82). Listing runs from the ledger and turning the committed
proof-checkpoint result into tables are logic, so they live here, testable without streamlit. The functions
take bytes, not paths into `var/`: the page reads files through `app.container`, and this module stays
free of the container (which wires LLM backends) so the no-LLM contract can hold for it.
Must not: import streamlit or the container, compute a rate, or type a verdict in; the verdict comes
from `proof_checkpoint.checkpoint` (ADR 0024), and every count is shown with its denominator.
No LLM is involved in this module.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pydantic import ValidationError

from bio_claim_check.app.freeze import ACTIVE_FREEZE
from bio_claim_check.app.run_record import LedgerRow, RunStatus
from bio_claim_check.app.usecases.proof_checkpoint import (
    ITEMS,
    MAX_FAILED,
    MAX_PARENTS_FLAGGED,
    MIN_MODEL_TRAPS_FLAGGED,
    MIN_PARENTS_PASSED,
    MODEL_TRAPS,
    PARENTS,
    POLICY,
    Checkpoint,
    Verdict,
    applies,
    checkpoint,
)
from bio_claim_check.common.errors import BccError
from bio_claim_check.features.traps.counts import DISPOSITIONS, TrapResult

type Viewable = Literal["run", "check"]
VIEWABLE_COMMANDS: Final[tuple[Viewable, ...]] = ("run", "check")

RUNS_LABEL: Final = "Most recently completed first"
"""The ledger records completions in order; a run's place in the list is when it finished."""

ABOUT_LABEL: Final = "Silver standard, planted, controlled paired design, exploratory."
"""How the trap counts are framed whatever the verdict (ADR 0023, ADR 0024 §3)."""

ADJUST_LABEL: Final = (
    "The verifier did not meet its predeclared bar: it was too cautious on correct claims. "
    "Read each claim's reason and evidence; do not read these counts as accuracy."
)
GO_LABEL: Final = "The verifier met its predeclared bar on this set. These are counts, not accuracy."
NO_RULE_LABEL: Final = "No predeclared rule applies to this result; the counts are shown without a verdict."


class LedgerError(BccError):
    """The run ledger has a line that is not a ledger row, so the list of runs cannot be trusted."""

    code = "ui.ledger"


class AboutLoadError(BccError):
    """The committed proof-checkpoint result is missing or is not a trap result."""

    code = "ui.about"


@dataclass(frozen=True, slots=True)
class RunEntry:
    """One recorded run the Trust report can show."""

    run_id: str
    command: Viewable
    finished_at: str

    @property
    def label(self) -> str:
        """Ledger facts only; whether a run is fake or live is read from its manifest once loaded."""
        return f"{self.finished_at} · {self.command} · {self.run_id}"


def list_runs(ledger: bytes) -> tuple[RunEntry, ...]:
    """Every successful `run` or `check` with a published run id, most recently completed first, once each.

    `run --dev` rows count too: their folder holds a viewable report. Failed rows and other commands are
    left out. A line that is not a ledger row raises `LedgerError` (no line is skipped silently).
    """
    entries: list[RunEntry] = []
    seen: set[str] = set()
    for number, line in reversed(list(enumerate(ledger.splitlines(), start=1))):
        if not line.strip():
            continue
        try:
            row = LedgerRow.model_validate_json(line)
        except ValidationError as err:
            raise LedgerError(
                f"run ledger line {number} is not a ledger row ({err.error_count()} errors)"
            ) from None
        command = _viewable(row.command)
        if command is None or row.status is not RunStatus.SUCCEEDED or row.run_id is None:
            continue
        if row.run_id in seen:
            continue
        seen.add(row.run_id)
        entries.append(RunEntry(row.run_id, command, row.finished_at.isoformat()))
    return tuple(entries)


def _viewable(command: str) -> Viewable | None:
    for known in VIEWABLE_COMMANDS:
        if command == known:
            return known
    return None


@dataclass(frozen=True, slots=True)
class CountView:
    """One row of the trap disposition counts: k of n per disposition, never a rate."""

    kind: str
    role: str
    generator: str
    n: int
    passed: int
    needs_review: int
    flagged: int
    failed: int
    exact: int


@dataclass(frozen=True, slots=True)
class PairTableView:
    """One trap-by-parent table (rows: the trap's disposition; columns: its parent's)."""

    kind: str
    generator: str
    n: int
    discriminated: int
    table: tuple[tuple[int, ...], ...]


@dataclass(frozen=True, slots=True)
class RuleLine:
    """One of the four predeclared conditions, with the total it read."""

    name: str
    value: int
    denominator: int
    bound: str
    met: bool


@dataclass(frozen=True, slots=True)
class AboutView:
    """The complete S13p result as the About page shows it: every count row and pair table (R9)."""

    label: str
    framing: str
    policy: str
    verdict: str | None
    rules: tuple[RuleLine, ...]
    rows: tuple[CountView, ...]
    pairs: tuple[PairTableView, ...]
    dispositions: tuple[str, ...]
    verifier: str
    writer_family_flag: bool


def load_about(path: Path) -> AboutView:
    """Read the committed result and build the About view; `AboutLoadError` if it cannot be read."""
    try:
        raw = path.read_bytes()
    except OSError as err:
        raise AboutLoadError(
            f"cannot read the proof-checkpoint result {path}: {err.strerror or err}"
        ) from None
    return about_view(raw)


def about_view(raw: bytes) -> AboutView:
    """Every count row and pair table of the result, and the verdict code computes from it (ADR 0024)."""
    try:
        result = TrapResult.model_validate_json(raw)
    except (ValidationError, json.JSONDecodeError) as err:
        raise AboutLoadError(f"the proof-checkpoint result is not a trap result: {err}") from None
    point = checkpoint(result, ACTIVE_FREEZE) if applies(result, ACTIVE_FREEZE) else None
    return AboutView(
        label=ABOUT_LABEL,
        framing=_framing(point),
        policy=POLICY,
        verdict=None if point is None else point.verdict.value,
        rules=() if point is None else _rules(point),
        rows=tuple(
            CountView(
                kind=r.kind.value,
                role=r.role,
                generator=r.generator,
                n=r.n,
                passed=r.passed,
                needs_review=r.needs_review,
                flagged=r.flagged,
                failed=r.failed,
                exact=r.exact,
            )
            for r in result.counts.rows
        ),
        pairs=tuple(
            PairTableView(
                kind=p.kind.value, generator=p.generator, n=p.n, discriminated=p.discriminated, table=p.table
            )
            for p in result.counts.pairs
        ),
        dispositions=tuple(d.value for d in DISPOSITIONS),
        verifier=result.verifier,
        writer_family_flag=result.writer_family_flag,
    )


def _framing(point: Checkpoint | None) -> str:
    if point is None:
        return NO_RULE_LABEL
    return GO_LABEL if point.verdict is Verdict.GO else ADJUST_LABEL


def _rules(point: Checkpoint) -> tuple[RuleLine, ...]:
    return (
        RuleLine(
            "model traps flagged",
            point.model_traps_flagged,
            MODEL_TRAPS,
            f"≥ {MIN_MODEL_TRAPS_FLAGGED}",
            point.model_traps_flagged >= MIN_MODEL_TRAPS_FLAGGED,
        ),
        RuleLine(
            "parents passed",
            point.parents_passed,
            PARENTS,
            f"≥ {MIN_PARENTS_PASSED}",
            point.parents_passed >= MIN_PARENTS_PASSED,
        ),
        RuleLine(
            "parents flagged",
            point.parents_flagged,
            PARENTS,
            f"≤ {MAX_PARENTS_FLAGGED}",
            point.parents_flagged <= MAX_PARENTS_FLAGGED,
        ),
        RuleLine("failed", point.failed, ITEMS, f"≤ {MAX_FAILED}", point.failed <= MAX_FAILED),
    )
