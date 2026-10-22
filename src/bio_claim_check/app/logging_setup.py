"""[RING:app] Logging, configured once from `Settings` where a command loads them, with secrets redacted.

Why: until S08b one module logged through stdlib `logging` with no configuration, so the format and level
depended on whoever imported us. Now every logger under `bio_claim_check` writes one line per record to
stderr (stdout stays data only), as JSON or as text (`Settings.log_format`), at `Settings.log_level`.
The package logger does not propagate and owns exactly one handler, so a host's root handler never sees
our records and calling this twice never doubles lines. Fields passed via `extra=` whose key names a
secret (`api_key`, `X-Api-Key`, `authorization`, `*_token`, `user_agent`, ...) are replaced by
`[redacted]`, recursively, on a copy: the record is never mutated (invariant I50). Lines carry no
timestamp: the package reads no wall clock,
and log lines are not part of any byte-identity guarantee.
Must not: read the environment, write to stdout, or put a secret into a message string (redaction is by
key; callers pass identifiers as `extra` fields, never credentials).
"""

import logging
import math
import re
import sys
from collections.abc import Mapping, Sequence
from typing import Final, cast, override

from bio_claim_check.app.settings import Settings
from bio_claim_check.common.canonical_json import compact_json

PACKAGE_LOGGER: Final = "bio_claim_check"
REDACTED: Final = "[redacted]"
_SECRET_KEYS: Final = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "token",
        "secret",
        "password",
        "contact_email",
        "email",
        "cookie",
        "user_agent",  # ours carries the contact email (Europe PMC etiquette)
    }
)
_SECRET_SUFFIXES: Final = ("_key", "_token", "_secret", "_password", "_authorization", "_cookie", "_email")
_CAMEL_BOUNDARY: Final = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_RECORD_FIELDS: Final = frozenset(
    set(vars(logging.LogRecord("", logging.INFO, "", 0, "", None, None))) | {"message", "asctime", "taskName"}
)


def is_secret_key(key: str) -> bool:
    """Match after normalising header and camelCase spellings (`X-Api-Key` → `x_api_key`)."""
    normalised = _CAMEL_BOUNDARY.sub("_", key).replace("-", "_").lower()
    return normalised in _SECRET_KEYS or normalised.endswith(_SECRET_SUFFIXES)


def _clean(key: str, value: object) -> object:
    if is_secret_key(key):
        return REDACTED
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(k): _clean(str(k), v) for k, v in mapping.items()}
    if isinstance(value, list | tuple):
        items = cast(Sequence[object], value)
        return [_clean("", item) for item in items]
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    return str(value)


def extra_fields(record: logging.LogRecord) -> dict[str, object]:
    """The `extra=` fields of a record, redacted, as a new dict (the record is left untouched)."""
    return {k: _clean(k, v) for k, v in vars(record).items() if k not in _RECORD_FIELDS}


class JsonFormatter(logging.Formatter):
    """One compact JSON object per record: level, logger, event, then the redacted extra fields."""

    @override
    def format(self, record: logging.LogRecord) -> str:
        body: dict[str, object] = {**extra_fields(record)}
        body |= {"level": record.levelname, "logger": record.name, "event": record.getMessage()}
        if record.exc_info and record.exc_info[0] is not None:
            body["exc_type"] = record.exc_info[0].__name__  # the type only: a message may quote input
        return compact_json(body)


class TextFormatter(logging.Formatter):
    """`LEVEL logger: event key=value ...` for a person reading a terminal."""

    @override
    def format(self, record: logging.LogRecord) -> str:
        pairs = "".join(f" {k}={v}" for k, v in sorted(extra_fields(record).items()))
        return f"{record.levelname} {record.name}: {record.getMessage()}{pairs}"


def configure_logging(settings: Settings) -> logging.Logger:
    """Point the package logger at stderr with the configured format and level; safe to call again."""
    logger = logging.getLogger(PACKAGE_LOGGER)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if settings.log_format == "json" else TextFormatter())
    logger.addHandler(handler)
    logger.setLevel(settings.log_level)
    logger.propagate = False
    return logger
