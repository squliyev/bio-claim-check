"""[RING:features/corpus] Is the dataset intact? One pure check for CI, `corpus verify` and `corpus seal`.

Why: the test split is only "held out" if nobody can quietly edit it after it was frozen. `SEALED` holds
the sha256 of `manifest.json`; the manifest holds the sha256 of every data file and of the spec file. So
one line in `SEALED` pins every byte, and this module re-derives everything the manifest claims (hashes,
splits, candidate counts, audit order) instead of trusting it (invariants I38, I41, I42).
Must not: read or write files (callers pass bytes in), repair anything, or stop at the first problem:
the author needs every problem at once.

No LLM is involved in this module.
"""

from collections.abc import Mapping
from typing import Final

from pydantic import BaseModel, ValidationError

from bio_claim_check.features.contracts.corpus import (
    AuditRecord,
    CorpusManifest,
    CorpusSpec,
    CorpusSplit,
    Question,
    QuestionEntry,
    SourceEntry,
)
from bio_claim_check.features.corpus.audit_sheet import audit_ids
from bio_claim_check.features.corpus.layout import (
    DATA_FILES,
    MANIFEST,
    QUESTIONS,
    README,
    SEALED,
    SPEC,
    audit_file,
    candidate_counts,
    sources_file,
)
from bio_claim_check.features.corpus.serialise import model_sha256, sha256_hex

_QUESTION_FIELDS: Final = frozenset(Question.model_fields)


def sealed_bytes(manifest: bytes) -> bytes:
    """The content of `SEALED`: the manifest's sha256 and a newline."""
    return (sha256_hex(manifest) + "\n").encode()


def _rows[M: BaseModel](name: str, data: bytes, model: type[M], problems: list[str]) -> list[M]:
    rows: list[M] = []
    for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), start=1):
        try:
            rows.append(model.model_validate_json(line))
        except ValidationError as err:
            problems.append(f"{name} line {number}: {err.errors()[0]['msg']}")
    return rows


def _manifest(files: Mapping[str, bytes], problems: list[str]) -> CorpusManifest | None:
    try:
        return CorpusManifest.model_validate_json(files[MANIFEST])
    except ValidationError as err:
        problems.append(f"{MANIFEST}: {err.errors()[0]['msg']}")
        return None


def _allowed(spec: CorpusSpec) -> set[str]:
    audits = {audit_file(split, kind) for split in CorpusSplit for kind in spec.trap_kinds}
    return {SPEC, MANIFEST, SEALED, README, *DATA_FILES, *audits}


def dataset_problems(files: Mapping[str, bytes], spec: CorpusSpec, *, require_seal: bool = True) -> list[str]:
    """Every reason the dataset is not intact, or [] if it is.

    `files` maps each path relative to the dataset folder to its bytes; `spec` is `corpus.yaml` parsed by
    the caller. With `require_seal=False` a missing `SEALED` is fine (the state just before sealing), but
    a `SEALED` that does not match is always a problem.
    """
    problems = [f"{name} is not part of the dataset" for name in sorted(files.keys() - _allowed(spec))]
    required = [SPEC, MANIFEST, *DATA_FILES, *([SEALED] if require_seal else [])]
    missing = [name for name in required if name not in files]
    problems += [f"{name} is missing" for name in missing]
    if MANIFEST in missing:
        return problems

    seal = sha256_hex(files[MANIFEST])
    if SEALED in files and files[SEALED] != sealed_bytes(files[MANIFEST]):
        problems.append(f"{SEALED} does not match {MANIFEST}")
    manifest = _manifest(files, problems)
    if manifest is None:
        return problems

    hashed = {f.name: f.sha256 for f in manifest.files}
    if set(hashed) != set(DATA_FILES):
        problems.append(f"{MANIFEST} must hash exactly {', '.join(DATA_FILES)}")
    for name, digest in sorted(hashed.items()):
        if name in files and sha256_hex(files[name]) != digest:
            problems.append(f"{name} does not match its hash in {MANIFEST}")
    if SPEC in files and sha256_hex(files[SPEC]) != manifest.spec_file_sha256:
        problems.append(f"{SPEC} does not match spec_file_sha256 in {MANIFEST}")
    if model_sha256(spec) != manifest.spec_sha256:
        problems.append(f"the parsed spec does not match spec_sha256 in {MANIFEST}")
    if missing:
        return problems

    before = len(problems)
    entries = _sources(files, spec, problems)
    _questions(files, spec, problems)
    if len(problems) == before and tuple(candidate_counts(spec, entries)) != manifest.candidate_counts:
        problems.append(f"candidate_counts in {MANIFEST} do not match the sources")
    problems += _audits(files, spec, entries, seal)
    return problems


def _sources(files: Mapping[str, bytes], spec: CorpusSpec, problems: list[str]) -> list[SourceEntry]:
    entries: list[SourceEntry] = []
    for split in CorpusSplit:
        name = sources_file(split)
        for entry in _rows(name, files[name], SourceEntry, problems):
            if entry.split is not split:
                problems.append(f"{name}: {entry.source_id} is marked {entry.split.value}")
            entries.append(entry)

    ids = [e.source_id for e in entries]
    problems += [f"{s} appears more than once" for s in sorted({s for s in ids if ids.count(s) > 1})]
    known = {q.id for q in spec.questions}
    for e in entries:
        unknown = [r.question_id for r in e.ranks if r.question_id not in known]
        problems += [f"{e.source_id} ranks unknown question {q}" for q in unknown]

    split_of_cluster: dict[str, set[CorpusSplit]] = {}
    for e in entries:
        split_of_cluster.setdefault(e.cluster_id, set()).add(e.split)
    problems += [f"cluster {c} spans dev and test" for c, s in sorted(split_of_cluster.items()) if len(s) > 1]

    held_out = {q.id for q in spec.questions if q.domain == spec.held_out_domain()}
    problems += [
        f"{e.source_id} was retrieved by a held-out question but is in dev"
        for e in entries
        if e.split is CorpusSplit.DEV and any(r.question_id in held_out for r in e.ranks)
    ]
    return entries


def _questions(files: Mapping[str, bytes], spec: CorpusSpec, problems: list[str]) -> None:
    built = {q.id: q for q in _rows(QUESTIONS, files[QUESTIONS], QuestionEntry, problems)}
    if sorted(built) != sorted(q.id for q in spec.questions):
        problems.append(f"{QUESTIONS} must hold exactly the spec's questions")
        return
    for q in spec.questions:
        if built[q.id].model_dump(include=set(_QUESTION_FIELDS)) != q.model_dump():
            problems.append(f"{QUESTIONS}: {q.id} differs from the spec")


def _audits(files: Mapping[str, bytes], spec: CorpusSpec, entries: list[SourceEntry], seal: str) -> list[str]:
    problems: list[str] = []
    for split in CorpusSplit:
        for kind in spec.trap_kinds:
            name = audit_file(split, kind)
            if name not in files:
                continue
            try:
                record = AuditRecord.model_validate_json(files[name])
            except ValidationError as err:
                problems.append(f"{name}: {err.errors()[0]['msg']}")
                continue
            if (record.split, record.kind) != (split, kind):
                problems.append(f"{name} holds the audit of {record.split.value}/{record.kind.value}")
            if record.corpus_seal != seal:
                problems.append(f"{name} was made for a different seal")
            expected = audit_ids(entries, split, kind, salt=spec.audit_salt, n=spec.audit_n)
            if [d.source_id for d in record.decisions] != expected:
                problems.append(f"{name} must decide exactly the first {len(expected)} candidates in order")
    return problems
