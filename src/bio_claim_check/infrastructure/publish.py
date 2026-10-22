"""[RING:infrastructure] Publish bytes to a file exactly once: never overwrite, never half-write.

Why: run artifacts are content-addressed and cited, so a published file must never change. The bytes
are written to a uniquely named temp file in the target folder, fsynced, then hard-linked into place
(`os.link` fails if the name exists), so two concurrent writers cannot replace each other. Replaced the
report-specific `run_store` of S05 (S05b): canonical bytes and the run id now live in
`features.report.canonical`, and the app composes the two.
Must not: know what the bytes mean, overwrite different content (identical bytes are a no-op;
anything else raises), or write outside `folder` (`name` must be one plain file name).

No LLM is involved in this module.
"""

import os
import tempfile
from pathlib import Path, PurePath

from bio_claim_check.common.errors import BccError


class PublishError(BccError):
    """A file could not be published without losing or corrupting data."""

    code = "files.publish"


def _check_name(name: str) -> None:
    if (
        not name
        or name in {".", ".."}
        or "\0" in name
        or "/" in name
        or "\\" in name
        or PurePath(name).is_absolute()
    ):
        raise PublishError(f"{name!r} is not a plain file name")


def publish_once(folder: Path, name: str, data: bytes) -> Path:
    """Write `data` to `folder/name` once and return the path; identical existing bytes are a no-op."""
    _check_name(name)
    target = folder / name
    folder.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return _same_or_refuse(target, data)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=folder)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, target)
        except FileExistsError:
            return _same_or_refuse(target, data)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def _same_or_refuse(target: Path, data: bytes) -> Path:
    if target.read_bytes() == data:
        return target
    raise PublishError(f"{target} exists with different content; refusing to overwrite")
