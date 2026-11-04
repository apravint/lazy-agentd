import os
import shutil
import signal
import socket
import sys
import tempfile
import textwrap
import time
import unittest

from lazy_agentd.proxy import LazyProxy

from .helpers import free_port, get, port_open, run_cli, wait_for_port

BACKEND = textwrap.dedent(
    """
    import os, sys, http.server
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"backend:" + self.path.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a):
            pass
    open(sys.argv[2], "a").write(f"{os.getpid()}\\n")
    http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
    """
)


class TestLazyProxyConfig(unittest.TestCase):
    def test_placeholder_required_without_backend_port(self):
        with self.assertRaises(ValueError):
            LazyProxy("ollama serve")

    def test_placeholder_substituted(self):
        p = LazyProxy("uvicorn app:app --port {port}", backend_port=1234)
        self.assertEqual(p.argv, ["uvicorn", "app:app", "--port", "1234"])


class TestLazyProxyEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.script = os.path.join(self.tmp, "backend.py")
        self.log = os.path.join(self.tmp, "starts.log")
        with open(self.script, "w") as f:
            f.write(BACKEND)
        self.port = free_port()
        self.backend_port = free_port()

    def start_proxy(self, idle):
        target = f"{sys.executable} {self.script} {{port}} {self.log}"
        proc = run_cli("-p", str(self.port), "--idle-timeout", str(idle),
                       "--target", target, "--backend-port", str(self.backend_port))
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        self.assertTrue(wait_for_port(self.port), "proxy did not start listening")
        return proc

    def starts(self):
        if not os.path.exists(self.log):
            return 0
        with open(self.log) as f:
            return len(f.readlines())

    def test_lazy_start_proxy_and_idle_shutdown(self):
        proc = self.start_proxy(idle=1.5)
        time.sleep(0.5)
        self.assertEqual(self.starts(), 0, "backend must not start before first request")

        self.assertEqual(get(self.port, "/hello"), (200, b"backend:/hello"))
        self.assertEqual(get(self.port, "/again"), (200, b"backend:/again"))
        self.assertEqual(self.starts(), 1, "backend should start exactly once")

        out, _ = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, out)
        self.assertFalse(port_open(self.backend_port), "backend should be stopped")
        self.assertIn("Idle for", out)

    def test_connect_and_close_does_not_wake_backend(self):
        proc = self.start_proxy(idle=30)  # start_proxy already probes the port
        for _ in range(3):
            socket.create_connection(("127.0.0.1", self.port)).close()
        time.sleep(1.5)
        self.assertEqual(self.starts(), 0)
        proc.terminate()
        proc.communicate(timeout=10)

    def test_server_speaks_first_protocol(self):
        # A client that connects and waits must still reach the backend.
        proc = self.start_proxy(idle=30)
        c = socket.create_connection(("127.0.0.1", self.port))
        c.settimeout(10)
        deadline = time.monotonic() + 10
        while self.starts() == 0 and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(self.starts(), 1, "backend should start for a silent client")
        c.sendall(b"GET /late HTTP/1.0\r\n\r\n")
        data = b""
        while chunk := c.recv(4096):
            data += chunk
        c.close()
        self.assertTrue(data.endswith(b"backend:/late"))
        proc.terminate()
        proc.communicate(timeout=10)

    def test_restarts_backend_after_crash(self):
        proc = self.start_proxy(idle=30)
        self.assertEqual(get(self.port)[0], 200)
        with open(self.log) as f:
            os.kill(int(f.read().split()[0]), signal.SIGKILL)
        deadline = time.monotonic() + 5
        while port_open(self.backend_port) and time.monotonic() < deadline:
            time.sleep(0.1)
        time.sleep(1.5)  # let the watchdog notice
        self.assertEqual(get(self.port)[0], 200)
        self.assertEqual(self.starts(), 2)
        proc.terminate()
        proc.communicate(timeout=10)
        self.assertFalse(port_open(self.backend_port))

    def test_backend_that_never_listens(self):
        proc = run_cli("-p", str(self.port), "--idle-timeout", "1", "--startup-timeout", "1",
                       "--target", f"{sys.executable} -c 'import time; time.sleep(60)'",
                       "--backend-port", str(self.backend_port))
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        self.assertTrue(wait_for_port(self.port))
        with self.assertRaises(Exception):
            get(self.port, timeout=5)
        out, _ = proc.communicate(timeout=15)
        self.assertIn("not accepting connections", out)


if __name__ == "__main__":
    unittest.main()
