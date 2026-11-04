"""
Systemd socket-activation helpers (a small, dependency-free ``sd_listen_fds``).
"""

from __future__ import annotations

import logging
import os
import socket
from typing import List, MutableMapping, Optional

log = logging.getLogger("lazy_agentd")

#: First file descriptor systemd passes to an activated service.
SD_LISTEN_FDS_START = 3

_LISTEN_ENV = ("LISTEN_PID", "LISTEN_FDS", "LISTEN_FDNAMES")


def listen_fds(
    env: Optional[MutableMapping[str, str]] = None,
    start: int = SD_LISTEN_FDS_START,
) -> List[socket.socket]:
    """Return the listening sockets systemd passed to this process.

    Mirrors ``sd_listen_fds(unset_environment=1)``:

    * the sockets are only claimed if ``LISTEN_PID`` matches our PID, so a
      process that merely inherited the variables doesn't steal them;
    * ``LISTEN_*`` variables are removed so child processes (e.g. a backend
      started by proxy mode) don't think they were socket-activated;
    * the descriptors are marked non-inheritable.

    The socket family (IPv4, IPv6, Unix) is detected from the descriptor.
    """
    if env is None:
        env = os.environ

    raw_pid = env.get("LISTEN_PID")
    raw_fds = env.get("LISTEN_FDS")
    if raw_fds is None:
        return []

    try:
        if raw_pid is not None and int(raw_pid) != os.getpid():
            # Meant for another process (e.g. our parent); leave it alone.
            return []
        count = int(raw_fds)
    except ValueError:
        log.warning("Ignoring malformed LISTEN_PID/LISTEN_FDS environment")
        return []
    finally:
        if raw_pid is None or raw_pid == str(os.getpid()):
            for key in _LISTEN_ENV:
                env.pop(key, None)

    socks = []
    for fd in range(start, start + count):
        sock = socket.socket(fileno=fd)
        sock.set_inheritable(False)
        socks.append(sock)
    return socks


def bind_socket(host: str, port: int, backlog: int = 128) -> socket.socket:
    """Create a listening TCP socket on ``host:port`` (IPv4 or IPv6)."""
    family, type_, proto, _, addr = socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE
    )[0]
    sock = socket.socket(family, type_, proto)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(addr)
        sock.listen(backlog)
    except BaseException:
        sock.close()
        raise
    return sock


def acquire_listen_socket(host: str, port: int) -> socket.socket:
    """Use the systemd-passed socket if there is one, else bind ``host:port``."""
    socks = listen_fds()
    if socks:
        for extra in socks[1:]:
            log.warning("Ignoring extra activated socket %s", describe(extra))
            extra.close()
        log.info("Activated via systemd socket passing (%s)", describe(socks[0]))
        return socks[0]
    sock = bind_socket(host, port)
    log.info("Listening directly on %s", describe(sock))
    return sock


def describe(sock: socket.socket) -> str:
    """Human-readable address of a listening socket."""
    addr = sock.getsockname()
    if sock.family == socket.AF_UNIX:
        return f"unix:{addr}"
    host, port = addr[0], addr[1]
    if sock.family == socket.AF_INET6:
        host = f"[{host}]"
    return f"{host}:{port}"
