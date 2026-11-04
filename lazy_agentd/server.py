"""
Lazy-Agentd socket-activated HTTP server for in-process Python handlers.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional, Tuple, Type

from .activation import acquire_listen_socket

log = logging.getLogger("lazy_agentd")


class ActivatedHTTPServer(ThreadingHTTPServer):
    """A threaded HTTP server that serves on an existing listening socket and
    tracks activity, so callers can tell when it has gone idle.

    Pass either ``sock`` (ownership is taken), ``fd`` (it is duplicated; the
    caller keeps its own copy), or neither to bind ``host:port``.
    """

    daemon_threads = True

    def __init__(
        self,
        RequestHandlerClass: Type[BaseHTTPRequestHandler],
        fd: Optional[int] = None,
        host: str = "127.0.0.1",
        port: int = 9090,
        sock: Optional[socket.socket] = None,
    ):
        if sock is None and fd is not None:
            sock = socket.socket(fileno=socket.dup(fd))
        if sock is None:
            super().__init__((host, port), RequestHandlerClass, bind_and_activate=True)
        else:
            self.address_family = sock.family
            super().__init__((host, 0), RequestHandlerClass, bind_and_activate=False)
            # TCPServer.__init__ created a throwaway socket; replace it.
            self.socket.close()
            self.socket = sock
            self.server_address = sock.getsockname()
            if sock.family == socket.AF_UNIX:
                self.server_name, self.server_port = "localhost", 0
            else:
                self.server_name = socket.getfqdn(str(self.server_address[0]))
                self.server_port = int(self.server_address[1])

        self._activity_lock = threading.Lock()
        self.active_requests = 0
        self.last_activity = time.monotonic()

    def get_request(self) -> Tuple[socket.socket, Any]:
        conn, addr = super().get_request()
        if self.socket.family == socket.AF_UNIX:
            # BaseHTTPRequestHandler expects a (host, port) tuple.
            addr = ("unix", 0)
        return conn, addr

    def touch(self) -> None:
        """Mark the server as active right now."""
        with self._activity_lock:
            self.last_activity = time.monotonic()

    def idle_seconds(self) -> float:
        """Seconds since the last request finished (0 while any is in flight)."""
        with self._activity_lock:
            if self.active_requests:
                return 0.0
            return time.monotonic() - self.last_activity

    # Counted in the accepting thread, so the idle check can never miss a
    # request that has been accepted but not yet started.
    def process_request(self, request: Any, client_address: Any) -> None:
        with self._activity_lock:
            self.active_requests += 1
            self.last_activity = time.monotonic()
        super().process_request(request, client_address)

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._activity_lock:
                self.active_requests -= 1
                self.last_activity = time.monotonic()


class LazyDaemonServer:
    """Serve ``handler_class`` until it has been idle for ``idle_timeout``
    seconds, then return so the process can exit and free its memory.

    Uses the systemd-activated socket when present, else binds ``host:port``.
    ``idle_timeout=0`` disables hibernation.
    """

    def __init__(
        self,
        handler_class: Type[BaseHTTPRequestHandler],
        port: int = 9090,
        idle_timeout: float = 900,
        host: str = "127.0.0.1",
        poll_interval: float = 1.0,
    ):
        self.handler_class = handler_class
        self.port = port
        self.idle_timeout = idle_timeout
        self.host = host

        sock = acquire_listen_socket(host, port)
        self.httpd = ActivatedHTTPServer(handler_class, sock=sock)
        self.httpd.timeout = poll_interval

    @property
    def last_activity(self) -> float:
        return self.httpd.last_activity

    def touch(self) -> None:
        """Reset the idle timer (e.g. from background work you want to count)."""
        self.httpd.touch()

    def serve_forever(self) -> None:
        log.info("Idle hibernation timeout set to %ss", self.idle_timeout)
        try:
            while True:
                self.httpd.handle_request()
                if self.idle_timeout > 0 and self.httpd.idle_seconds() >= self.idle_timeout:
                    log.info(
                        "Idle for %ss. Exiting to free memory.", self.idle_timeout
                    )
                    break
        except KeyboardInterrupt:
            log.info("Interrupted, shutting down")
        finally:
            self.httpd.server_close()
