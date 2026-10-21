"""I31: offline tests cannot reach the network, in-process or in a Python subprocess."""

import os
import socket
import subprocess
import sys

import httpx
import pytest

from tests.conftest import is_live, scrubbed
from tests.support.netblock.sitecustomize import NetworkBlockedError

pytestmark = pytest.mark.arch

# 192.0.2.0/24 and 2001:db8::/32 are documentation ranges (RFC 5737, RFC 3849): never routable
PROBE = """
import socket

def connect(family, address, ex=False):
    with socket.socket(family) as s:
        return s.connect_ex(address) if ex else s.connect(address)

results = []
for name, attempt in [
    ("ipv4", lambda: connect(socket.AF_INET, ("192.0.2.1", 80))),
    ("ipv6", lambda: connect(socket.AF_INET6, ("2001:db8::1", 80))),
    ("connect_ex", lambda: connect(socket.AF_INET, ("192.0.2.1", 80), ex=True)),
    ("dns", lambda: socket.getaddrinfo("example.org", 443)),
    ("create_connection", lambda: socket.create_connection(("192.0.2.1", 80), timeout=1).close()),
]:
    try:
        attempt()
        results.append(f"{name}:open")
    except Exception as exc:
        results.append(f"{name}:{type(exc).__name__}")
a, b = socket.socketpair()
with a, b:
    a.sendall(b"x")
    results.append("unix:" + b.recv(1).decode())
print(" ".join(results))
"""
BLOCKED = (
    "ipv4:NetworkBlockedError ipv6:NetworkBlockedError connect_ex:NetworkBlockedError "
    "dns:NetworkBlockedError create_connection:NetworkBlockedError unix:x"
)


def test_in_process_attempts_are_blocked() -> None:
    namespace: dict[str, object] = {}
    exec(PROBE.replace("print(", "RESULT = ("), namespace)  # noqa: S102 -- fixed probe script above
    assert namespace["RESULT"] == BLOCKED


def test_a_real_http_client_is_blocked() -> None:
    with httpx.Client() as client, pytest.raises((NetworkBlockedError, httpx.ConnectError)):
        client.get("https://example.org")


def test_python_subprocesses_are_blocked() -> None:
    done = subprocess.run(  # noqa: S603 -- this interpreter, fixed probe, no shell
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True, timeout=60
    )
    assert done.stdout.strip() == BLOCKED


def test_only_live_tests_are_exempt(request: pytest.FixtureRequest) -> None:
    assert is_live({"live": pytest.mark.live.mark})
    assert not is_live({"live": True})  # a node named `live` (e.g. the tests/live/ folder) is not the marker
    assert not is_live({"e2e": pytest.mark.e2e.mark})
    assert not is_live(request.keywords)  # this very test runs blocked


def test_only_live_tests_see_the_contact_address() -> None:
    names = ["BCC_CONTACT_EMAIL", "BCC_FOUNDRY__API_KEY", "PATH"]
    assert scrubbed(names, live=False) == ["BCC_CONTACT_EMAIL", "BCC_FOUNDRY__API_KEY"]
    assert scrubbed(names, live=True) == ["BCC_FOUNDRY__API_KEY"]
    assert not [name for name in os.environ if name.startswith("BCC_")]  # and the fixture applied it here


def test_the_block_names_the_fix() -> None:
    with pytest.raises(NetworkBlockedError, match="mark it `live`"):
        socket.create_connection(("192.0.2.1", 80))
