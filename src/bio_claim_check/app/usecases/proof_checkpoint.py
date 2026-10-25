"""[RING:app/usecases] The proof checkpoint's predeclared go/adjust verdict on dev-v1 (ADR 0024).

Why: the demo track needed one decision from the first trap run, namely how S17a and H1 frame the
verifier. Deciding after the numbers are seen is a forking path. The rule was committed before any trap was
verified, and here code produces the verdict, not a person. CI recomputes it from the committed result and
checks it against the verdict line in dev-log S13p.
Why here and not in the traps slice: the policy is a demo decision about one set, not a generic trap
measure. Its thresholds are integers for dev-v1's exact composition (15 model traps, 16 parents, 38
items), so the policy is bound to that set's sha256 and refuses anything else rather than rescaling.
Must not: tune the judge, hide counts (both verdicts show the full k-of-n tables; the verdict changes the
framing only), or apply to another set.
No LLM is involved in this module.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from bio_claim_check.common.errors import BccError
from bio_claim_check.features.traps.counts import TrapResult

POLICY: Final = "adr-0024-v1"
DEV_V1_SHA256: Final = "b7d2b76d1490ca09030a1834ecd4c5afafa17b3030fcb280f0304dacb6f50593"
MODEL_TRAPS: Final = 15
PARENTS: Final = 16
ITEMS: Final = 38
MIN_MODEL_TRAPS_FLAGGED: Final = 10
MIN_PARENTS_PASSED: Final = 12
MAX_PARENTS_FLAGGED: Final = 3
MAX_FAILED: Final = 2


class CheckpointError(BccError):
    """The result is not dev-v1 as predeclared; the rule is not applied (ADR 0024)."""

    code = "traps.checkpoint"


class Verdict(StrEnum):
    GO = "GO"
    ADJUST = "ADJUST"


@dataclass(frozen=True)
class Checkpoint:
    """The four totals the rule reads, and the verdict they give."""

    model_traps_flagged: int
    parents_passed: int
    parents_flagged: int
    failed: int
    verdict: Verdict


def checkpoint(result: TrapResult) -> Checkpoint:
    """Apply ADR 0024 to a dev-v1 result; refuse another set or other denominators (fail closed)."""
    if result.trap_set_sha256 != DEV_V1_SHA256:
        raise CheckpointError("the ADR 0024 rule applies to dev-v1 only")
    rows = result.counts.rows
    model_traps = [r for r in rows if r.role == "trap" and r.generator == "model"]
    parents = [r for r in rows if r.role == "parent"]
    sizes = (sum(r.n for r in model_traps), sum(r.n for r in parents), sum(r.n for r in rows))
    if sizes != (MODEL_TRAPS, PARENTS, ITEMS):
        raise CheckpointError(f"dev-v1 should have {(MODEL_TRAPS, PARENTS, ITEMS)} items, got {sizes}")
    flagged = sum(r.flagged for r in model_traps)
    passed = sum(r.passed for r in parents)
    false_alarms = sum(r.flagged for r in parents)
    failed = sum(r.failed for r in rows)
    go = (
        flagged >= MIN_MODEL_TRAPS_FLAGGED
        and passed >= MIN_PARENTS_PASSED
        and false_alarms <= MAX_PARENTS_FLAGGED
        and failed <= MAX_FAILED
    )
    return Checkpoint(flagged, passed, false_alarms, failed, Verdict.GO if go else Verdict.ADJUST)


def describe(point: Checkpoint) -> str:
    """One line naming the policy, the four totals against their thresholds, and the verdict."""
    return (
        f"verdict ({POLICY}): {point.verdict.value}; model traps flagged {point.model_traps_flagged}/"
        f"{MODEL_TRAPS} (≥{MIN_MODEL_TRAPS_FLAGGED}), parents passed {point.parents_passed}/{PARENTS} "
        f"(≥{MIN_PARENTS_PASSED}), parents flagged {point.parents_flagged}/{PARENTS} "
        f"(≤{MAX_PARENTS_FLAGGED}), failed {point.failed}/{ITEMS} (≤{MAX_FAILED})"
    )
