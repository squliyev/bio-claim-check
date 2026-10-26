"""[RING:app/ui] The words the UI shows for each error code, written for a reader rather than a log.

Why: an exception's text names files, ids and internals; it is meant for the CLI and the logs. The page
shows curated copy instead, keyed by the stable `BccError.code` (docs/error-codes.md), and a generic line
for a code it does not know, so no raw exception text reaches the page (I83). Named `error_copy` rather
than `copy` so `streamlit run` never shadows the standard library's `copy` module.
Must not: import streamlit, format the exception's own message into the copy, or invent a code that
docs/error-codes.md does not list.
No LLM is involved in this module.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from bio_claim_check.common.errors import BccError

GENERIC: Final = "Something went wrong, and nothing was shown from it. The details are in the logs."

LIVE_UNAVAILABLE: Final = (
    "Live mode is unavailable: the settings it needs (such as BCC_CONTACT_EMAIL and a provider) are not "
    "configured. Recorded runs, fictional mode and the About page still work."
)

_LIVE_FAILED: Final = "The language model call failed, so no result was produced. Try again later."
_RECORD_FAILED: Final = "The run could not be fully saved under var/. The details are in the logs."

ERROR_COPY: Final[Mapping[str, str]] = MappingProxyType(
    {
        "runs.busy": "Another run or check is in progress. Wait for it to finish, then try again.",
        "run.input": "Enter a question, and a number of papers (k) of at least 1.",
        "check.input": (
            "Enter a claim of at most 1,000 characters without control characters, "
            "and a PMID of 1 to 9 digits "
            "(for example 12345678 or PMID:12345678)."
        ),
        "check.test_split": (
            "That paper is in the held-out test set, so it is not checked or shown. The test set stays "
            "unseen so it can measure the checker honestly later."
        ),
        "app.dataset_read": (
            "The sealed dataset this app needs to keep held-out papers out of live checks could not be "
            "read or failed its seal check, so nothing was run."
        ),
        "contracts.rule_pack": (
            "The installed rule pack could not be loaded, so nothing was checked. Reinstall the app."
        ),
        "retrieval.not_found": "Europe PMC has no paper with that PMID.",
        "retrieval.not_citable": (
            "That PMID is not a paper the verifier can check against: for example it has no abstract, is not "
            "in English, or is a kind of record (such as a letter or an editorial) that is excluded."
        ),
        "cache.miss": (
            "This app is in read-only (offline) mode and has no saved response for this request. Only "
            "requests made before can be replayed."
        ),
        "retrieval.failed": "Europe PMC could not be reached or sent a response that could not be read.",
        "cache.failed": "The local response cache could not be opened or written.",
        "llm.unknown_deployment": "A configured model deployment is not in the model catalogue.",
        "app.missing_provider": LIVE_UNAVAILABLE,
        "app.unsupported_provider": "A configured model's provider is not supported yet.",
        "llm.call_failed": _LIVE_FAILED,
        "llm.transport": "The model provider could not be reached. Try again later.",
        "llm.provider_rejected": (
            "The model provider refused the request (for example a key or deployment problem)."
        ),
        "llm.prompt_filtered": (
            "The model provider's content filter refused this request, so no result was produced."
        ),
        "llm.unsupported_request": _LIVE_FAILED,
        "llm.unexpected_response": (
            "The model provider sent a response in an unknown shape, so no result was produced."
        ),
        "llm.budget_exceeded": (
            "This run reached its limit of live model calls (BCC_MAX_LIVE_LLM_CALLS), so it was stopped and "
            "no result was produced."
        ),
        "answer.invalid_claims": (
            "The answering model wrote a claim that could not be checked (blank, uncited or citing a paper "
            "twice), so no result was produced."
        ),
        "events.write": _RECORD_FAILED,
        "files.publish": _RECORD_FAILED,
        "files.append": _RECORD_FAILED,
        "runs.published": (
            "This run cannot be shown: its files are missing, altered, or of a kind the app does not show."
        ),
        "ui.ledger": "The list of runs cannot be read: the run ledger has a line that is not a ledger row.",
        "ui.about": (
            "The verifier's proof-checkpoint result is missing or "
            "unreadable, so the About tables cannot be shown."
        ),
        "traps.checkpoint": (
            "The proof-checkpoint result is not the set its rule was declared for, so no verdict is shown."
        ),
    }
)
"""Curated copy per `BccError.code`; every key is listed in docs/error-codes.md (I83)."""


def message_for(err: BccError) -> str:
    """The curated copy for the error's code, or the generic line for a code without copy."""
    return ERROR_COPY.get(err.code, GENERIC)
