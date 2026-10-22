"""[RING:common] The base of every error this package raises on purpose, each with a stable code.

Why: until S08b nineteen error classes in every ring derived straight from stdlib exceptions, so nothing
said which failures were deliberate and documented and which were bugs. Each deliberate error now
derives from `BccError` and declares a dotted `code` (for example `cache.miss`) that never changes once
published. `docs/error-codes.md` lists every code and an architecture test keeps the two in step (I49).
Subclasses keep their stdlib base as well (`class CacheMissError(BccError, LookupError)`), so every
existing `except LookupError` still matches.
Must not: carry domain vocabulary, decide exit codes (that is the CLI's job), or format messages.

No LLM is involved in this module.
"""

import re
from typing import ClassVar, Final

CODE_PATTERN: Final = re.compile(r"^[a-z]+(\.[a-z_]+)+$")


class BccError(Exception):
    """A failure the package raises deliberately. Every subclass declares its own stable `code`."""

    code: ClassVar[str]
    """Dotted and stable, e.g. `cache.miss`. Declared by each subclass itself, never inherited; the
    architecture test `tests/arch/test_error_codes.py` enforces that, the pattern and uniqueness (no
    import-time hook, so importing a module never runs checks or registers anything)."""
