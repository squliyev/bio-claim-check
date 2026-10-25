"""[RING:app/usecases] Generate, audit, commit and verify the dev trap set (S13, ADR 0022).

Why: the trap set combines three slices (corpus for eligibility, traps for drafting and gating, verify for
judging) and only `app` may combine slices. Every abstract comes from its dev question's sealed pool
(`dev_papers`: seal check, dev question only, dev-split papers with their sealed hashes), so no test
source can reach the writer or the verifier (I78). The verifier receives a claim built from the item's
text alone; kind, role, pair and ground truth never leave this module (I69). `set_problems`,
`panel_problems` and `result_problems` are also what CI runs on every committed set, ledger and result
(I76, I77, I79). A model panel (ADR 0023) confirms a set when the author cannot: unanimous only, raters
from a closed registry, none of the writer's or the verifier's family.
Must not: do I/O itself, touch a test question or source, retry or drop an item, tune anything on trap
outcomes (the judge is frozen), or let a writer or verifier failure disappear (it is a counted row).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import ValidationError

from bio_claim_check.app.usecases.answer_dev import dev_papers
from bio_claim_check.common.canonical_json import compact_json, pretty_json_bytes
from bio_claim_check.common.errors import BccError
from bio_claim_check.common.model_family import ModelFamily
from bio_claim_check.common.text import CleanedText
from bio_claim_check.engine.events.emitter import EventEmitter
from bio_claim_check.engine.llm.model_spec import UnknownDeploymentError
from bio_claim_check.features.contracts.corpus import CorpusSpec, CorpusSplit, QuestionEntry, SourceEntry
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.labels import OverstatedReason
from bio_claim_check.features.contracts.outcome import PairOutcome
from bio_claim_check.features.contracts.paper import Paper
from bio_claim_check.features.contracts.rulepack import Rule, RulePack
from bio_claim_check.features.contracts.verdict import Claim
from bio_claim_check.features.corpus.layout import DEV_SOURCES, MANIFEST, QUESTIONS
from bio_claim_check.features.corpus.seal import dataset_problems
from bio_claim_check.features.corpus.serialise import sha256_hex
from bio_claim_check.features.retrieval.base_literature_source import BaseLiteratureSource
from bio_claim_check.features.traps.audit_sheet import confirmed_items, parse_decisions, sheet_csv
from bio_claim_check.features.traps.base_trap_writer import BaseTrapWriter
from bio_claim_check.features.traps.counts import TrapResult, counts
from bio_claim_check.features.traps.models import DraftRow, TrapDraft, TrapItem, TrapWriterFailure, opaque_id
from bio_claim_check.features.traps.panel import PanelLedger, kept_ids, ledger_rows, unanimous
from bio_claim_check.features.traps.rule_floor import mutate
from bio_claim_check.features.traps.sampling import Pick, sample
from bio_claim_check.features.traps.validity import claim_problems, contamination, pair_problems
from bio_claim_check.features.verify.base_verifier import BaseVerifier

SCORED_KINDS: Final = (
    OverstatedReason.BACKGROUND_AS_RESULT,
    OverstatedReason.CORRELATION_AS_CAUSATION,
    OverstatedReason.NONSIGNIFICANT_AS_EFFECT,
    OverstatedReason.PRECLINICAL_TO_CLINICAL,
    OverstatedReason.CERTAINTY_INFLATION,
)
"""The kinds the sieve proposes dev candidates for; surrogate traps wait for H1 (ADR 0022)."""

CALLS_PER_ITEM: Final = 2
"""A call plus at most one repair: the budget preflight refuses a run the budget cannot finish."""


class TrapInputError(BccError):
    """The dataset, a draft or a trap set cannot be used. One line per problem."""

    code = "traps.input"

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = tuple(problems)


class TrapPoolError(BccError):
    """A sampled or committed source did not come back, with its sealed hash, in its dev pool."""

    code = "traps.pool"


class TrapBudgetError(BccError):
    """`BCC_MAX_LIVE_LLM_CALLS` cannot cover the run; refused before any call."""

    code = "traps.budget"


@dataclass(frozen=True, slots=True)
class TrapWriterPorts:
    literature: BaseLiteratureSource
    writer: BaseTrapWriter
    rules: RulePack
    emitter: EventEmitter | None = None


@dataclass(frozen=True, slots=True)
class TrapVerifyPorts:
    literature: BaseLiteratureSource
    verifier: BaseVerifier
    rules: RulePack
    emitter: EventEmitter | None = None


def _rows[M: SourceEntry | QuestionEntry](data: bytes, model: type[M]) -> list[M]:
    return [model.model_validate_json(line) for line in data.decode("utf-8").splitlines()]


def _sealed(files: Mapping[str, bytes], spec: CorpusSpec) -> None:
    if problems := dataset_problems(files, spec):
        raise TrapInputError(["the dataset is not intact and sealed:", *problems])


def _budget(needed: int, max_live_calls: int | None) -> None:
    if max_live_calls is not None and max_live_calls < CALLS_PER_ITEM * needed:
        raise TrapBudgetError(
            f"{needed} item(s) need up to {CALLS_PER_ITEM * needed} live calls; "
            f"BCC_MAX_LIVE_LLM_CALLS is {max_live_calls}"
        )


def _pools(
    source: BaseLiteratureSource,
    files: Mapping[str, bytes],
    spec: CorpusSpec,
    wanted: Sequence[tuple[str, SourceId]],
    emitter: EventEmitter | None,
) -> dict[tuple[str, SourceId], Paper]:
    """Each wanted source's paper from its own question's dev pool; raises if one did not come back."""
    found: dict[tuple[str, SourceId], Paper] = {}
    for question_id in sorted({q for q, _ in wanted}):
        _, pool = dev_papers(source, files, spec, question_id, k=spec.pool_hits, emitter=emitter)
        found.update({(question_id, p.source_id): p for p in pool.papers})
    if missing := sorted({f"{s} ({q})" for q, s in wanted if (q, s) not in found}):
        raise TrapPoolError(f"{', '.join(missing)}: did not come back in the dev pool")
    return found


def _rule(pack: RulePack, kind: OverstatedReason) -> Rule:
    return next(r for r in pack.rules if r.reason is kind)


def plan_picks(
    files: Mapping[str, bytes],
    spec: CorpusSpec,
    per_kind: int,
    kinds: Sequence[OverstatedReason] = SCORED_KINDS,
) -> tuple[Pick, ...]:
    """The sources a run would draft, in order; raises before any fetch if the dataset or target fails."""
    _sealed(files, spec)
    questions = {q.id for q in _rows(files[QUESTIONS], QuestionEntry) if q.split is CorpusSplit.DEV}
    entries = _rows(files[DEV_SOURCES], SourceEntry)
    return sample(entries, kinds, per_kind, questions=questions, max_rank=spec.pool_hits)


def _draft_rows(
    pick: Pick, out: TrapDraft | TrapWriterFailure, paper: Paper, pack: RulePack, origin_id: str
) -> list[DraftRow]:
    pid = opaque_id(pick.source_id, "parent", None)
    common = {
        "pair_id": pid,
        "kind": pick.kind,
        "question_id": pick.question_id,
        "source_id": pick.source_id,
        "abstract_sha256": pick.abstract_sha256,
        "origin_id": origin_id,
    }
    if isinstance(out, TrapWriterFailure):
        return [
            DraftRow.model_validate(
                {
                    **common,
                    "id": pid,
                    "role": "parent",
                    "claim": None,
                    "generator": "model",
                    "rule": None,
                    "failure": out.kind,
                }
            )
        ]
    parent, trap = out.parent, out.trap
    abstract = paper.abstract
    rows = [
        DraftRow.model_validate(
            {
                **common,
                "id": pid,
                "role": "parent",
                "claim": parent,
                "generator": "model",
                "rule": None,
                "problems": tuple(claim_problems(parent, abstract, pack)),
            }
        ),
        DraftRow.model_validate(
            {
                **common,
                "id": opaque_id(pick.source_id, "trap", None),
                "role": "trap",
                "claim": trap,
                "generator": "model",
                "rule": None,
                "problems": tuple(claim_problems(trap, abstract, pack) + pair_problems(parent, trap)),
            }
        ),
    ]
    for floor in mutate(parent):
        rows.append(
            DraftRow.model_validate(
                {
                    **common,
                    "id": opaque_id(pick.source_id, "trap", floor.rule),
                    "role": "trap",
                    "claim": floor.claim,
                    "generator": "rule_floor",
                    "rule": floor.rule,
                    "problems": tuple(
                        claim_problems(floor.claim, abstract, pack) + pair_problems(parent, floor.claim)
                    ),
                }
            )
        )
    return rows


def generate(
    ports: TrapWriterPorts,
    files: Mapping[str, bytes],
    spec: CorpusSpec,
    *,
    per_kind: int,
    origin_id: str,
    max_live_calls: int | None,
    kinds: Sequence[OverstatedReason] = SCORED_KINDS,
) -> tuple[DraftRow, ...]:
    """Sample, preflight the budget, fetch the dev pools, draft each source once, gate every claim.

    Rows come out in pick order (parent, model trap, then rule-floor traps); a writer failure is one row.
    """
    picks = plan_picks(files, spec, per_kind, kinds)
    _budget(len(picks), max_live_calls)
    papers = _pools(
        ports.literature, files, spec, [(p.question_id, p.source_id) for p in picks], ports.emitter
    )
    rows: list[DraftRow] = []
    for pick in picks:
        paper = papers[(pick.question_id, pick.source_id)]
        out = ports.writer.draft(pick.kind, _rule(ports.rules, pick.kind), paper)
        rows.extend(_draft_rows(pick, out, paper, ports.rules, origin_id))
    return tuple(rows)


def draft_bytes(rows: Sequence[DraftRow]) -> bytes:
    """The draft file (`var/` only): one canonical JSON row per line."""
    return "".join(compact_json(r.model_dump(mode="json")) + "\n" for r in rows).encode("utf-8")


def parse_draft(data: bytes) -> tuple[DraftRow, ...]:
    try:
        rows = tuple(DraftRow.model_validate_json(line) for line in data.decode("utf-8").splitlines())
    except (UnicodeDecodeError, ValidationError):
        raise TrapInputError(["the draft file is not a valid trap draft"]) from None
    if not rows:
        raise TrapInputError(["the draft file is empty"])
    if data != draft_bytes(rows):
        raise TrapInputError(["the draft file is not in canonical form (was it edited?)"])
    return rows


def sheet_for(
    source: BaseLiteratureSource, draft: bytes, files: Mapping[str, bytes], spec: CorpusSpec
) -> str:
    """The audit sheet of a draft, with abstracts from the dev pools (replay `source` from the cache)."""
    rows = parse_draft(draft)
    _sealed(files, spec)
    papers = _pools(source, files, spec, sorted({(r.question_id, r.source_id) for r in rows}), None)
    abstracts: dict[SourceId, CleanedText] = {s: p.abstract for (_, s), p in papers.items()}
    return sheet_csv(rows, sha256_hex(draft), abstracts)


def set_bytes(items: Sequence[TrapItem]) -> bytes:
    """The committed set: one canonical JSON item per line, sorted by id."""
    ordered = sorted(items, key=lambda i: i.id)
    return "".join(compact_json(i.model_dump(mode="json")) + "\n" for i in ordered).encode("utf-8")


def apply_audit(
    draft: bytes, sheet: str, files: Mapping[str, bytes], spec: CorpusSpec, pack: RulePack
) -> bytes:
    """The committed set from a draft and its filled-in sheet; refuses a set that would fail CI."""
    rows = parse_draft(draft)
    _sealed(files, spec)
    items = confirmed_items(rows, parse_decisions(sheet, rows, sha256_hex(draft)))
    if not items:
        raise TrapInputError(["no row was confirmed; nothing to commit"])
    data = set_bytes(items)
    if problems := set_problems(data, files, spec, pack):
        raise TrapInputError(problems)
    return data


def ledger_bytes(ledger: PanelLedger) -> bytes:
    return pretty_json_bytes(ledger.model_dump(mode="json"))


def apply_panel(
    draft: bytes,
    sheets: Sequence[tuple[str, str]],
    files: Mapping[str, bytes],
    spec: CorpusSpec,
    pack: RulePack,
    *,
    protocol: bytes,
    intended_freeze: str,
    verifier_family: ModelFamily,
    rater_families: Mapping[str, ModelFamily],
    writer_family_of: Callable[[str], ModelFamily],
) -> tuple[bytes, bytes]:
    """The committed set and its ledger from one filled-in sheet per rater, `(rater id, sheet)` in order.

    A row is kept only if every rater confirmed it and its parent (ADR 0023). Refuses before reading a
    sheet if the panel is malformed, and refuses a set or ledger that would fail CI.
    """
    rows = parse_draft(draft)
    _sealed(files, spec)
    raters = tuple(r for r, _ in sheets)
    writers = _writer_families(rows, writer_family_of)
    if problems := _rater_problems(raters, rater_families, writers, verifier_family):
        raise TrapInputError(problems)
    draft_sha = sha256_hex(draft)
    panels = [parse_decisions(text, rows, draft_sha) for _, text in sheets]
    items = confirmed_items(rows, unanimous(panels), "model_panel")
    if not items:
        raise TrapInputError(["no row was confirmed by every rater; nothing to commit"])
    data = set_bytes(items)
    if problems := set_problems(data, files, spec, pack):
        raise TrapInputError(problems)
    ledger = ledger_bytes(
        PanelLedger(
            set_sha256=sha256_hex(data),
            draft_sha256=draft_sha,
            protocol_sha256=sha256_hex(protocol),
            intended_freeze=intended_freeze,
            raters=raters,
            sheet_sha256=tuple(sha256_hex(text.encode("utf-8")) for _, text in sheets),
            rows=ledger_rows(rows, panels),
        )
    )
    if problems := panel_problems(
        data,
        ledger,
        protocol=protocol,
        verifier_family=verifier_family,
        rater_families=rater_families,
        writer_family_of=writer_family_of,
    ):
        raise TrapInputError(problems)
    return data, ledger


def _writer_families(
    rows: Sequence[DraftRow | TrapItem], writer_family_of: Callable[[str], ModelFamily]
) -> frozenset[ModelFamily]:
    try:
        return frozenset(writer_family_of(w) for w in sorted({r.origin_id for r in rows}))
    except UnknownDeploymentError as err:
        raise TrapInputError([f"the trap writer is not in the model catalog: {err}"]) from None


def _rater_problems(
    raters: Sequence[str],
    rater_families: Mapping[str, ModelFamily],
    writer_families: frozenset[ModelFamily],
    verifier_family: ModelFamily,
) -> list[str]:
    """Declared family separation (I79): known raters, distinct families, none the writer's or verifier's.

    Family separation is conflict control, not statistical independence (ADR 0023).
    """
    if len(raters) < 2 or len(set(raters)) != len(raters):
        return ["a panel needs at least two distinct raters, one sheet each"]
    if unknown := [r for r in raters if r not in rater_families]:
        return [f"{', '.join(unknown)}: not a registered panel rater (app.models.RATER_FAMILIES)"]
    families = [rater_families[r] for r in raters]
    problems: list[str] = []
    if len(set(families)) != len(families):
        problems.append("two raters share a model family")
    if clash := sorted({f.value for f in families} & {w.value for w in writer_families}):
        problems.append(f"a rater shares the trap writer's family ({', '.join(clash)})")
    if verifier_family in families:
        problems.append(f"a rater shares the verifier's family ({verifier_family.value})")
    return problems


def panel_families(ledger: bytes, rater_families: Mapping[str, ModelFamily]) -> frozenset[ModelFamily]:
    """The families of a committed ledger's raters; a verifier of one of them must not judge the set."""
    try:
        raters = PanelLedger.model_validate_json(ledger).raters
    except ValidationError:
        raise TrapInputError(["the panel ledger is not valid"]) from None
    if unknown := [r for r in raters if r not in rater_families]:
        raise TrapInputError([f"{', '.join(unknown)}: not a registered panel rater"])
    return frozenset(rater_families[r] for r in raters)


def panel_problems(
    data: bytes,
    ledger: bytes | None,
    *,
    protocol: bytes,
    verifier_family: ModelFamily | None,
    rater_families: Mapping[str, ModelFamily],
    writer_family_of: Callable[[str], ModelFamily],
) -> list[str]:
    """Why a set's confirmation is not what it claims (I79); empty if it holds. Needs no abstract.

    A set without a ledger must be author-confirmed. With one, the ledger must belong to this set and to
    the committed protocol, its raters must be separated by family from the writer and from the intended
    freeze's verifier (`verifier_family`; `None` if that freeze is unknown), and the set must hold exactly
    the rows every rater confirmed whose parent every rater confirmed.
    """
    try:
        items = parse_set(data)
    except TrapInputError as err:
        return list(err.problems)
    panel = {i.id for i in items if i.confirmed_by == "model_panel"}
    if ledger is None:
        return [f"{len(panel)} model_panel item(s) but no panel ledger"] if panel else []
    try:
        parsed = PanelLedger.model_validate_json(ledger)
    except ValidationError as err:
        return [f"the panel ledger is not valid: {err.error_count()} problem(s)"]
    problems: list[str] = []
    if ledger != ledger_bytes(parsed):
        problems.append("the panel ledger is not in canonical form")
    if parsed.set_sha256 != sha256_hex(data):
        problems.append("the panel ledger is for another trap set")
    if parsed.protocol_sha256 != sha256_hex(protocol):
        problems.append("the panel ledger names another rater protocol than the committed one")
    if verifier_family is None:
        problems.append(f"the intended freeze {parsed.intended_freeze} is not a committed freeze record")
    else:
        try:
            writers = _writer_families(items, writer_family_of)
        except TrapInputError as err:
            return [*problems, *err.problems]
        problems.extend(_rater_problems(parsed.raters, rater_families, writers, verifier_family))
    if len(panel) != len(items):
        problems.append("a set with a panel ledger must be confirmed by the panel on every item")
    kept = kept_ids(parsed)
    if missing := sorted(kept - {i.id for i in items}):
        problems.append(f"confirmed by every rater but missing from the set: {', '.join(missing)}")
    if extra := sorted({i.id for i in items} - kept):
        problems.append(f"in the set but not confirmed by every rater: {', '.join(extra)}")
    rows = {r.id: r for r in parsed.rows}
    for item in items:
        row = rows.get(item.id)
        if row is not None and (row.pair_id, row.role, row.generator, row.kind) != (
            item.pair_id,
            item.role,
            item.generator,
            item.kind,
        ):
            problems.append(f"{item.id}: differs from its ledger row")
    return problems


def parse_set(data: bytes) -> tuple[TrapItem, ...]:
    try:
        items = tuple(TrapItem.model_validate_json(line) for line in data.decode("utf-8").splitlines())
    except UnicodeDecodeError:
        raise TrapInputError(["the trap set is not UTF-8"]) from None
    except ValidationError as err:
        raise TrapInputError([f"the trap set is not valid: {err.error_count()} problem(s)"]) from None
    if not items:
        raise TrapInputError(["the trap set is empty"])
    return items


def set_problems(data: bytes, files: Mapping[str, bytes], spec: CorpusSpec, pack: RulePack) -> list[str]:
    """Why a committed trap set breaks I76 or I77; empty if it holds. Needs no abstract (CI runs it).

    Everything a hand edit could change and CI can recompute is checked: the source is in its question's
    retrieved pool, the kind is a scored sieve candidate of the source, and a rule-floor claim is exactly
    the mutation of its parent. Whether a claim is true of the abstract stays the author's call.
    """
    try:
        items = parse_set(data)
    except TrapInputError as err:
        return list(err.problems)
    problems: list[str] = []
    if data != set_bytes(items):
        problems.append("the set is not canonical (one sorted JSON line per item, sorted by id)")
    if len({i.id for i in items}) != len(items):
        problems.append("duplicate ids")
    questions = {q.id: q for q in _rows(files[QUESTIONS], QuestionEntry)}
    sources = {e.source_id: e for e in _rows(files[DEV_SOURCES], SourceEntry)}
    parents = {i.id: i for i in items if i.role == "parent"}
    if len({p.source_id for p in parents.values()}) != len(parents):
        problems.append("a source has more than one parent")
    for item in items:
        question = questions.get(item.question_id)
        entry = sources.get(item.source_id)
        if question is None or question.split is not CorpusSplit.DEV:
            problems.append(f"{item.id}: {item.question_id} is not a dev question")
        elif entry is None or entry.split is not CorpusSplit.DEV:
            problems.append(f"{item.id}: {item.source_id} is not a dev source")
        elif not any(r.question_id == item.question_id and r.rank <= spec.pool_hits for r in entry.ranks):
            problems.append(f"{item.id}: {item.source_id} is not in the pool of {item.question_id}")
        elif item.abstract_sha256 != entry.abstract_sha256:
            problems.append(f"{item.id}: abstract_sha256 differs from the sealed dataset")
        elif item.kind not in SCORED_KINDS or not any(c.kind is item.kind for c in entry.candidates):
            problems.append(f"{item.id}: {item.kind.value} is not a scored sieve candidate of its source")
        parent = parents.get(item.pair_id)
        if parent is None:
            problems.append(f"{item.id}: its parent {item.pair_id} is not in the set")
        elif (parent.source_id, parent.question_id, parent.kind) != (
            item.source_id,
            item.question_id,
            item.kind,
        ):
            problems.append(f"{item.id}: differs from its parent in source, question or kind")
        elif item.generator == "rule_floor" and (item.rule, item.claim) not in {
            (f.rule, f.claim) for f in mutate(parent.claim)
        }:
            problems.append(f"{item.id}: not the {item.rule} rule-floor mutation of its parent")
        problems.extend(f"{item.id}: {p}" for p in contamination(item.claim, pack))
    return problems


def verify_set(
    ports: TrapVerifyPorts,
    data: bytes,
    files: Mapping[str, bytes],
    spec: CorpusSpec,
    *,
    judge_sha256: str,
    verifier: str,
    verifier_family: ModelFamily,
    family_of: Callable[[str], ModelFamily],
    max_live_calls: int | None,
    rater_families: frozenset[ModelFamily] = frozenset(),
) -> TrapResult:
    """Judge every item once, as a live run judges a pair. Bad input raises before any fetch.

    `rater_families` are the families of the panel that confirmed the set (empty for the author); a
    verifier of one of them would be judged against its own family's labels (I79).
    """
    if problems := set_problems(data, files, spec, ports.rules):
        raise TrapInputError(problems)
    if verifier_family in rater_families:
        raise TrapInputError([f"the verifier shares a panel rater's family ({verifier_family.value})"])
    _sealed(files, spec)
    items = parse_set(data)
    flag = _writer_family_flag(items, verifier_family, family_of)
    _budget(len(items), max_live_calls)
    papers = _pools(
        ports.literature, files, spec, [(i.question_id, i.source_id) for i in items], ports.emitter
    )
    outcomes = tuple(
        PairOutcome.of(
            item.id,
            ports.verifier.verify(
                Claim(id=item.id, text=item.claim, cites=(item.source_id,)),
                papers[(item.question_id, item.source_id)],
                ports.rules,
            ),
        )
        for item in items
    )
    return TrapResult(
        trap_set_sha256=sha256_hex(data),
        corpus_seal=sha256_hex(files[MANIFEST]),
        judge_sha256=judge_sha256,
        verifier=verifier,
        writer_family_flag=flag,
        outcomes=outcomes,
        counts=counts(items, outcomes),
    )


def _writer_family_flag(
    items: Sequence[TrapItem], verifier_family: ModelFamily, family_of: Callable[[str], ModelFamily]
) -> bool:
    """Whether any writer shares the verifier's family; an unknown writer is refused before any call."""
    try:
        return any(family_of(w) is verifier_family for w in sorted({i.origin_id for i in items}))
    except UnknownDeploymentError as err:
        raise TrapInputError([f"the trap writer is not in the model catalog: {err}"]) from None


def trap_result_bytes(result: TrapResult) -> bytes:
    return pretty_json_bytes(result.model_dump(mode="json"))


def result_problems(
    data: bytes,
    result: bytes,
    files: Mapping[str, bytes],
    *,
    judge_sha256: str,
    verifier: str,
    family_of: Callable[[str], ModelFamily],
    rater_families: frozenset[ModelFamily] = frozenset(),
) -> list[str]:
    """Why a committed result does not belong to this set, dataset and frozen judge, or miscounts (I76).

    `judge_sha256` and `verifier` come from the freeze record the result is named after. Self-reported,
    like the challenge result: it proves consistency, not that a model produced it.
    """
    try:
        items = parse_set(data)
        recorded = TrapResult.model_validate_json(result)
    except TrapInputError as err:
        return list(err.problems)
    except ValidationError as err:
        return [f"the result is not valid: {err.error_count()} problem(s)"]
    problems: list[str] = []
    if result != trap_result_bytes(recorded):
        problems.append("the result is not in canonical form")
    if recorded.trap_set_sha256 != sha256_hex(data):
        problems.append("the result is for another trap set")
    if recorded.corpus_seal != sha256_hex(files[MANIFEST]):
        problems.append("the result is for another sealed dataset")
    if (recorded.judge_sha256, recorded.verifier) != (judge_sha256, verifier):
        problems.append("the result names another judge or verifier than its freeze record")
    try:
        flag = _writer_family_flag(items, family_of(verifier), family_of)
    except (TrapInputError, UnknownDeploymentError) as err:
        return [*problems, str(err)]
    if recorded.writer_family_flag != flag:
        problems.append("writer_family_flag does not match the writers and the verifier")
    if family_of(verifier) in rater_families:
        problems.append("the verifier shares a panel rater's family (I79)")
    try:
        again = counts(items, recorded.outcomes)
    except ValueError as err:
        return [*problems, str(err)]
    if again != recorded.counts:
        problems.append("the recorded counts do not match the outcomes")
    return problems
