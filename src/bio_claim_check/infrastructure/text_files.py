"""[RING:infrastructure] Read UTF-8 text from a file or from data shipped inside the package.

Why: the app reads hand-written documents (rule packs) from user paths and from package data; one
small reader gives both the same error shape, so callers report "cannot read" uniformly.
Must not: interpret the text, or import features or engine (transport only).

No LLM is involved in this module.
"""

from importlib.resources import files
from pathlib import Path

from bio_claim_check.common.errors import BccError


class ReadError(BccError):
    """A file could not be read as UTF-8 text. The message names the path."""

    code = "files.read"


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        raise ReadError(f"{path}: cannot read: {err}") from None


def read_package_text(*parts: str) -> str:
    """Text of a file shipped inside `bio_claim_check`, e.g. ``("data", "rulepacks", "default.yaml")``."""
    try:
        return read_package_bytes(*parts).decode("utf-8")
    except UnicodeDecodeError as err:
        raise ReadError(f"package data {'/'.join(parts)}: cannot read: {err}") from None


def read_package_bytes(*parts: str) -> bytes:
    """Raw bytes of a file shipped inside `bio_claim_check` (hash these, then decode them)."""
    resource = files("bio_claim_check").joinpath(*parts)
    try:
        return resource.read_bytes()
    except OSError as err:
        raise ReadError(f"package data {'/'.join(parts)}: cannot read: {err}") from None
