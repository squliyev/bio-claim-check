"""[TEST SUPPORT] Make every internet connection attempt raise (I31). Unix sockets and pipes still work.

Imported two ways: by the root conftest (patched per test with monkeypatch), and by Python itself at the
start of a subprocess whose `PYTHONPATH` holds this directory (then `install()` runs at import).
Blocks `socket.connect`/`connect_ex` for AF_INET/AF_INET6, `create_connection` and `getaddrinfo` (DNS).
Connectionless UDP (`sendto` without `connect`) is not blocked: no dependency uses it, and a tripwire, not a
sandbox, is the goal.
"""

import socket
from collections.abc import Callable
from typing import Any

_INET = (socket.AF_INET, socket.AF_INET6)
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


class NetworkBlockedError(RuntimeError):
    """An offline test tried to reach the network. Mark it `live` if that is intended."""


def _deny(what: str) -> None:
    raise NetworkBlockedError(f"offline test tried to open a network connection ({what}); mark it `live`")


def _connect(self: socket.socket, address: Any) -> None:
    if self.family in _INET:
        _deny(f"connect {address!r}")
    _real_connect(self, address)


def _connect_ex(self: socket.socket, address: Any) -> int:
    if self.family in _INET:
        _deny(f"connect_ex {address!r}")
    return _real_connect_ex(self, address)


def _create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
    del args, kwargs
    _deny(f"create_connection {address!r}")
    raise AssertionError("unreachable")


def _getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> list[Any]:
    del args, kwargs
    _deny(f"getaddrinfo {host!r}")
    raise AssertionError("unreachable")


PATCHES: tuple[tuple[object, str, Callable[..., Any]], ...] = (
    (socket.socket, "connect", _connect),
    (socket.socket, "connect_ex", _connect_ex),
    (socket, "create_connection", _create_connection),
    (socket, "getaddrinfo", _getaddrinfo),
)


def install() -> None:
    for target, name, replacement in PATCHES:
        setattr(target, name, replacement)


if __name__ == "sitecustomize":
    install()
