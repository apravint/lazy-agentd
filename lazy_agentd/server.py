"""
Lazy-Agentd Socket-Activated Server Engine
"""

import sys
import os
import time
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Type

class ActivatedHTTPServer(HTTPServer):
    def __init__(self, RequestHandlerClass, fd: Optional[int] = None, host: str = "127.0.0.1", port: int = 9090):
        self.address_family = socket.AF_INET
        if fd is not None:
            # Systemd socket activation passed via FD 3
            super().__init__((host, 0), RequestHandlerClass, bind_and_activate=False)
            self.socket = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)
        else:
            super().__init__((host, port), RequestHandlerClass, bind_and_activate=True)

class LazyDaemonServer:
    def __init__(
        self,
        handler_class: Type[BaseHTTPRequestHandler],
        port: int = 9090,
        idle_timeout: int = 900,
        host: str = "127.0.0.1"
    ):
        self.handler_class = handler_class
        self.port = port
        self.idle_timeout = idle_timeout
        self.host = host
        self.last_activity = time.time()

        # Check for systemd socket activation
        listen_fds = int(os.environ.get("LISTEN_FDS", 0))
        if listen_fds > 0:
            print("⚡ [lazy-agentd] Activated via systemd socket passing (FD 3)")
            self.httpd = ActivatedHTTPServer(handler_class, fd=3)
        else:
            print(f"⚡ [lazy-agentd] Listening directly on http://{host}:{port}")
            self.httpd = ActivatedHTTPServer(handler_class, port=port, host=host)

        self.httpd.timeout = 5.0

    def touch(self):
        """Update last active timestamp."""
        self.last_activity = time.time()

    def serve_forever(self):
        print(f"🔋 Idle hibernation timeout set to {self.idle_timeout}s.")
        try:
            while True:
                self.httpd.handle_request()
                if self.idle_timeout > 0 and (time.time() - self.last_activity > self.idle_timeout):
                    print(f"💤 [lazy-agentd] Dormant for {self.idle_timeout}s. Exiting to free RAM/GPU context.")
                    break
        except KeyboardInterrupt:
            print("\nShutting down server.")
        finally:
            self.httpd.server_close()
