"""[RING:common] The one canonical JSON serialisation that every hash and every written file uses.

Why: until S08b five inline `json.dumps` copies in four modules (corpus files, report bytes, cache keys,
prompt hashes) each restated the same options, and one had already drifted (only the cache key refused
NaN). Two named variants keep today's bytes exactly: `compact_json` for lines and hashes, `pretty_json`
for documents reviewed in a diff. Both sort keys, keep non-ASCII text as UTF-8 and refuse NaN and
infinity, which are not JSON (invariant I48; an architecture test bans `json.dumps` elsewhere in `src`).
Must not: change the bytes of either variant (golden and characterisation tests pin them), accept
non-JSON values, or perform I/O.

No LLM is involved in this module.
"""

import hashlib
import json


def compact_json(value: object) -> str:
    """Sorted keys, no whitespace, UTF-8 text kept as is; NaN and infinity raise `ValueError`."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def pretty_json(value: object) -> str:
    """Sorted keys, two-space indent, UTF-8 text kept as is; no trailing newline."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)


def pretty_json_bytes(value: object) -> bytes:
    """`pretty_json` plus one trailing newline, encoded as UTF-8: the bytes of a written document."""
    return (pretty_json(value) + "\n").encode("utf-8")


def compact_sha256(value: object) -> str:
    """sha256 (hex) of the UTF-8 bytes of `compact_json(value)`."""
    return hashlib.sha256(compact_json(value).encode("utf-8")).hexdigest()
