"""[RING:features/corpus] Canonical bytes and hashes for the corpus files (invariant I37).

Why: the dataset claim is "the same spec, cache, tool version and declared date give the same bytes".
That only holds if every file is written one way: sorted keys, no ASCII escaping, compact JSON lines,
`\n` endings, rows in an order the caller fixes. Hashes of the cleaned abstract and of each question's
ranked pool let anyone who re-fetches later see exactly what drifted, without redistributing text.
Must not: write files (publishing is infrastructure's job) or include timestamps, paths or durations.

No LLM is involved in this module.
"""

import hashlib
from collections.abc import Iterable, Sequence

from pydantic import BaseModel

from bio_claim_check.common.canonical_json import compact_json, pretty_json_bytes
from bio_claim_check.features.contracts.ids import SourceId
from bio_claim_check.features.contracts.paper import Paper


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _line(value: object) -> str:
    return compact_json(value)


def jsonl_bytes(rows: Iterable[BaseModel]) -> bytes:
    """One compact JSON object per line, in the order given; empty input gives empty bytes."""
    return "".join(_line(row.model_dump(mode="json")) + "\n" for row in rows).encode()


def document_bytes(model: BaseModel) -> bytes:
    """A single JSON document, indented for review in a diff."""
    return pretty_json_bytes(model.model_dump(mode="json"))


def model_sha256(model: BaseModel) -> str:
    """Hash of a model's canonical compact JSON (used for the spec)."""
    return sha256_hex(_line(model.model_dump(mode="json")).encode())


def abstract_sha256(paper: Paper) -> str:
    """Hash of the cleaned abstract the sieve and the verifier read."""
    return sha256_hex(paper.abstract.encode())


def pool_sha256(pool: Sequence[tuple[SourceId, str]]) -> str:
    """Hash of a question's ranked pool as (source_id, abstract_sha256) pairs, in rank order."""
    return sha256_hex(_line([list(pair) for pair in pool]).encode())
