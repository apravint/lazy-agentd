"""
Proxy mode: start a real backend (Ollama, uvicorn, an HTTP MCP server, ...)
on the first connection, forward TCP traffic to it, and stop it again once
nothing has used it for ``idle_timeout`` seconds.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import signal
import socket
import time
from typing import List, Optional, Sequence, Union

from .activation import acquire_listen_socket

log = logging.getLogger("lazy_agentd")

_CHUNK = 64 * 1024

#: Seconds to wait for a client's first byte before starting the backend anyway.
FIRST_BYTE_WAIT = 1.0


class BackendError(RuntimeError):
    pass


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


class LazyProxy:
    """On-demand TCP proxy in front of a backend command.

    ``command`` may contain ``{port}``, replaced by the backend port. If
    ``backend_port`` is not given, a free port is picked and ``{port}`` is
    required so the backend knows where to listen.
    """

    def __init__(
        self,
        command: Union[str, Sequence[str]],
        backend_port: Optional[int] = None,
        backend_host: str = "127.0.0.1",
        listen_host: str = "127.0.0.1",
        listen_port: int = 9090,
        idle_timeout: float = 900,
        startup_timeout: float = 60,
        stop_timeout: float = 10,
    ):
        argv = shlex.split(command) if isinstance(command, str) else list(command)
        if not argv:
            raise ValueError("target command is empty")
        has_placeholder = any("{port}" in a for a in argv)
        if backend_port is None:
            if not has_placeholder:
                raise ValueError(
                    "target command needs a {port} placeholder, or pass backend_port"
                )
            backend_port = free_port(backend_host)
        self.argv: List[str] = [a.replace("{port}", str(backend_port)) for a in argv]
        self.backend_host = backend_host
        self.backend_port = backend_port
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.idle_timeout = idle_timeout
        self.startup_timeout = startup_timeout
        self.stop_timeout = stop_timeout

        self._proc: Optional[asyncio.subprocess.Process] = None
        self._active = 0
        self._last_activity = time.monotonic()

    # -- public -----------------------------------------------------------

    def run(self) -> int:
        asyncio.run(self._main())
        return 0

    # -- internals ----------------------------------------------------------

    def _touch(self) -> None:
        self._last_activity = time.monotonic()

    async def _main(self) -> None:
        self._stop = asyncio.Event()
        self._backend_lock = asyncio.Lock()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._stop.set)

        sock = acquire_listen_socket(self.listen_host, self.listen_port)
        server = await asyncio.start_server(self._handle, sock=sock)
        log.info(
            "Proxying to %s:%s, backend: %s (idle timeout %ss)",
            self.backend_host,
            self.backend_port,
            shlex.join(self.argv),
            self.idle_timeout,
        )
        watchdog = asyncio.create_task(self._watchdog())
        try:
            await self._stop.wait()
        finally:
            server.close()
            watchdog.cancel()
            await self._stop_backend()

    async def _watchdog(self) -> None:
        interval = 1.0 if self.idle_timeout <= 0 else min(1.0, self.idle_timeout / 4)
        while True:
            await asyncio.sleep(interval)
            proc = self._proc
            if proc is not None and proc.returncode is not None:
                log.warning("Backend exited with code %s", proc.returncode)
                self._proc = None
            if (
                self.idle_timeout > 0
                and self._active == 0
                and time.monotonic() - self._last_activity >= self.idle_timeout
            ):
                log.info("Idle for %ss. Stopping backend and exiting.", self.idle_timeout)
                self._stop.set()
                return

    async def _handle(
        self, client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter
    ) -> None:
        self._active += 1
        self._touch()
        backend_w: Optional[asyncio.StreamWriter] = None
        try:
            # Wait for the client to say something before waking the backend,
            # so health checks and port scans that just connect and close
            # don't start it. Server-speaks-first protocols (MySQL, SMTP) send
            # nothing, so start anyway if the connection stays open.
            try:
                first = await asyncio.wait_for(client_r.read(_CHUNK), FIRST_BYTE_WAIT)
                if not first:
                    return  # closed without sending anything
            except asyncio.TimeoutError:
                first = b""
            except (ConnectionError, OSError):
                return
            try:
                await self._ensure_backend()
                backend_r, backend_w = await asyncio.open_connection(
                    self.backend_host, self.backend_port
                )
            except (BackendError, OSError) as exc:
                log.error("Cannot reach backend: %s", exc)
                return
            if first:
                backend_w.write(first)
            await asyncio.gather(
                self._pipe(client_r, backend_w), self._pipe(backend_r, client_w)
            )
        finally:
            self._active -= 1
            self._touch()
            for w in (client_w, backend_w):
                if w is not None:
                    w.close()

    async def _pipe(self, src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
        try:
            while True:
                data = await src.read(_CHUNK)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
                self._touch()
            if dst.can_write_eof():
                dst.write_eof()
        except (ConnectionError, OSError):
            dst.close()

    async def _ensure_backend(self) -> None:
        async with self._backend_lock:
            if self._proc is not None and self._proc.returncode is None:
                return
            log.info("Starting backend: %s", shlex.join(self.argv))
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    *self.argv, start_new_session=True
                )
            except OSError as exc:
                raise BackendError(f"failed to start {self.argv[0]!r}: {exc}") from exc
            await self._wait_ready(self._proc)

    async def _wait_ready(self, proc: asyncio.subprocess.Process) -> None:
        started = time.monotonic()
        deadline = started + self.startup_timeout
        while True:
            if proc.returncode is not None:
                raise BackendError(f"backend exited with code {proc.returncode} during startup")
            try:
                _, w = await asyncio.open_connection(self.backend_host, self.backend_port)
            except OSError:
                if time.monotonic() >= deadline:
                    await self._stop_backend()
                    raise BackendError(
                        f"backend not accepting connections on "
                        f"{self.backend_host}:{self.backend_port} after {self.startup_timeout}s"
                    ) from None
                await asyncio.sleep(0.1)
                continue
            w.close()
            log.info("Backend ready in %.2fs", time.monotonic() - started)
            return

    async def _stop_backend(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.returncode is not None:
            return
        log.info("Stopping backend (pid %s)", proc.pid)
        self._signal_group(proc, signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), self.stop_timeout)
        except asyncio.TimeoutError:
            log.warning("Backend ignored SIGTERM for %ss, killing", self.stop_timeout)
            self._signal_group(proc, signal.SIGKILL)
            await proc.wait()

    @staticmethod
    def _signal_group(proc: asyncio.subprocess.Process, sig: int) -> None:
        # The backend runs in its own session, so this also reaches any
        # worker processes it spawned.
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass
