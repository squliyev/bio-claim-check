"""Logging: configured from Settings, stderr only, and never shows a secret-keyed field (I50)."""

import json
import logging
from typing import override

import pytest
from tests.support.settings import make_settings

from bio_claim_check.app import cli
from bio_claim_check.app.logging_setup import PACKAGE_LOGGER, REDACTED, configure_logging, is_secret_key

pytestmark = pytest.mark.unit

SENTINEL = "SENTINEL-not-a-real-secret-7f3a"


def _lines(err: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in err.splitlines() if line]


def test_json_lines_go_to_stderr_with_redacted_secrets(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(make_settings(log_level="INFO"))
    logging.getLogger(f"{PACKAGE_LOGGER}.features.x").info(
        "fetched %d",
        3,
        extra={
            "api_key": SENTINEL,
            "headers": {"Authorization": SENTINEL, "accept": "json"},
            "attempts": [{"session_token": SENTINEL}],
            "source_id": "PMID:1",
        },
    )
    out, err = capsys.readouterr()
    assert out == ""
    assert SENTINEL not in err
    [line] = _lines(err)
    assert line == {
        "level": "INFO",
        "logger": "bio_claim_check.features.x",
        "event": "fetched 3",
        "api_key": REDACTED,
        "headers": {"Authorization": REDACTED, "accept": "json"},
        "attempts": [{"session_token": REDACTED}],
        "source_id": "PMID:1",
    }


def test_the_record_itself_is_never_mutated(capsys: pytest.CaptureFixture[str]) -> None:
    seen: list[logging.LogRecord] = []

    class Keep(logging.Handler):
        @override
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record)

    logger = configure_logging(make_settings())
    logger.addHandler(Keep())
    logger.warning("w", extra={"api_key": SENTINEL})
    assert seen[0].__dict__["api_key"] == SENTINEL
    assert SENTINEL not in capsys.readouterr().err


def test_a_host_root_handler_never_sees_our_records(capsys: pytest.CaptureFixture[str]) -> None:
    root_seen: list[logging.LogRecord] = []

    class Spy(logging.Handler):
        @override
        def emit(self, record: logging.LogRecord) -> None:
            root_seen.append(record)

    spy = Spy()
    logging.getLogger().addHandler(spy)
    try:
        configure_logging(make_settings())
        logging.getLogger(PACKAGE_LOGGER).error("boom", extra={"password": SENTINEL})
    finally:
        logging.getLogger().removeHandler(spy)
    assert root_seen == []
    assert SENTINEL not in capsys.readouterr().err


def test_configuring_twice_gives_one_line_per_record(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(make_settings())
    configure_logging(make_settings())
    logging.getLogger(PACKAGE_LOGGER).warning("once")
    assert len(_lines(capsys.readouterr().err)) == 1


def test_level_comes_from_settings(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(make_settings(log_level="ERROR"))
    logging.getLogger(PACKAGE_LOGGER).warning("hidden")
    assert capsys.readouterr().err == ""


def test_default_level_keeps_info_quiet(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(make_settings())
    logging.getLogger(PACKAGE_LOGGER).info("progress")
    assert capsys.readouterr().err == ""


def test_text_format_is_for_people_and_still_redacts(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(make_settings(log_format="text"))
    logging.getLogger(PACKAGE_LOGGER).warning("slow", extra={"api_key": SENTINEL, "n": 2})
    assert capsys.readouterr().err == f"WARNING bio_claim_check: slow api_key={REDACTED} n=2\n"


def test_exceptions_log_their_type_only(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(make_settings())
    try:
        raise ValueError(SENTINEL)
    except ValueError:
        logging.getLogger(PACKAGE_LOGGER).exception("failed")
    err = capsys.readouterr().err
    assert SENTINEL not in err
    assert _lines(err)[0]["exc_type"] == "ValueError"


def test_odd_values_are_logged_as_text_never_crash(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(make_settings())
    logging.getLogger(PACKAGE_LOGGER).warning("odd", extra={"ratio": float("nan"), "obj": object, "f": 0.5})
    line = _lines(capsys.readouterr().err)[0]
    assert (line["ratio"], line["obj"], line["f"]) == ("nan", "<class 'object'>", 0.5)


@pytest.mark.parametrize(
    ("key", "secret"),
    [
        ("api_key", True),
        ("API_KEY", True),
        ("Authorization", True),
        ("contact_email", True),
        ("refresh_token", True),
        ("client_secret", True),
        ("api-key", True),
        ("x-api-key", True),
        ("X-Api-Key", True),
        ("Proxy-Authorization", True),
        ("set-cookie", True),
        ("Cookie", True),
        ("accessToken", True),
        ("sessionToken", True),
        ("apiKey", True),
        ("User-Agent", True),
        ("userEmail", True),
        ("source_id", False),
        ("sourceId", False),
        ("input_tokens", False),
        ("cache-key-namespace", False),
        ("tokens", False),
        ("keyword", False),
    ],
)
def test_secret_keys(key: str, secret: bool) -> None:
    assert is_secret_key(key) is secret


def test_cli_configures_logging_right_after_settings_load(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setenv("BCC_CONTACT_EMAIL", "someone@example.org")
    monkeypatch.setattr(cli, "configure_logging", lambda settings: calls.append(settings.log_format))  # pyright: ignore[reportUnknownLambdaType, reportUnknownMemberType, reportUnknownArgumentType] - spy
    settings = cli._settings(cli.Path("absent.env"))  # pyright: ignore[reportPrivateUsage] - the bootstrap seam under test
    assert calls == [settings.log_format]
