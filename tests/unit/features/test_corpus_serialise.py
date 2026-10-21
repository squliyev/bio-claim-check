"""Canonical bytes (I37): the corpus files are a pure function of their rows."""

import hashlib
import json

from tests.support.papers import paper

from bio_claim_check.features.contracts.corpus import FileHash
from bio_claim_check.features.corpus.serialise import (
    abstract_sha256,
    document_bytes,
    jsonl_bytes,
    model_sha256,
    pool_sha256,
    sha256_hex,
)

ROW = FileHash(name="é/x.jsonl", sha256="a" * 64)


def test_jsonl_is_compact_sorted_utf8_and_newline_terminated() -> None:
    assert jsonl_bytes([ROW, ROW]) == ('{"name":"é/x.jsonl","sha256":"' + "a" * 64 + '"}\n').encode() * 2
    assert jsonl_bytes([]) == b""


def test_document_is_indented_with_a_trailing_newline() -> None:
    data = document_bytes(ROW)
    assert data.endswith(b"}\n")
    assert json.loads(data) == {"name": "é/x.jsonl", "sha256": "a" * 64}
    assert b"\n  " in data
    assert "é".encode() in data


def test_hashes_are_sha256_of_the_canonical_text() -> None:
    assert sha256_hex(b"x") == hashlib.sha256(b"x").hexdigest()
    assert model_sha256(ROW) == sha256_hex(jsonl_bytes([ROW]).rstrip(b"\n"))


def test_abstract_hash_is_of_the_cleaned_text() -> None:
    p = paper(abstract="A <i>cleaned</i> &lt; text.")
    assert abstract_sha256(p) == sha256_hex(b"A cleaned < text.")


def test_pool_hash_depends_on_order_and_content() -> None:
    a, b = ("MED:1", "a" * 64), ("MED:2", "b" * 64)
    assert pool_sha256([a, b]) != pool_sha256([b, a])
    assert pool_sha256([a, b]) != pool_sha256([a, ("MED:2", "c" * 64)])
    assert pool_sha256([]) == sha256_hex(b"[]")
