import os
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler

from lazy_agentd.server import ActivatedHTTPServer, LazyDaemonServer

from .helpers import get


class DummyHandler(BaseHTTPRequestHandler):
    delay = 0.0

    def do_GET(self):
        time.sleep(self.delay)
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass


class SlowHandler(DummyHandler):
    delay = 2.5


def start(handler, idle_timeout):
    srv = LazyDaemonServer(handler_class=handler, port=0, idle_timeout=idle_timeout, poll_interval=0.1)
    port = srv.httpd.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port, t


class TestLazyDaemonServer(unittest.TestCase):
    def test_serves_requests(self):
        srv, port, t = start(DummyHandler, idle_timeout=5)
        self.assertEqual(get(port), (200, b"OK"))
        srv.idle_timeout = 0.01
        t.join(3)

    def test_exits_when_idle(self):
        _, _, t = start(DummyHandler, idle_timeout=0.5)
        t.join(3)
        self.assertFalse(t.is_alive())

    def test_steady_traffic_keeps_it_alive(self):
        # Regression: the idle timer used to start at boot and never reset,
        # so a busy server exited idle_timeout seconds after starting.
        srv, port, t = start(DummyHandler, idle_timeout=1.0)
        for _ in range(8):
            self.assertEqual(get(port)[0], 200)
            time.sleep(0.4)
        self.assertTrue(t.is_alive())
        t.join(3)
        self.assertFalse(t.is_alive())

    def test_in_flight_request_blocks_exit(self):
        _, port, t = start(SlowHandler, idle_timeout=0.5)
        self.assertEqual(get(port), (200, b"OK"))  # takes 2.5s > idle_timeout
        t.join(3)
        self.assertFalse(t.is_alive())

    def test_requests_are_concurrent(self):
        srv, port, t = start(SlowHandler, idle_timeout=5)
        results = []
        workers = [threading.Thread(target=lambda: results.append(get(port))) for _ in range(3)]
        t0 = time.monotonic()
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        self.assertLess(time.monotonic() - t0, 2.5 * 2)
        self.assertEqual(len(results), 3)
        srv.idle_timeout = 0.01
        t.join(3)

    def test_touch_resets_timer(self):
        srv, _, t = start(DummyHandler, idle_timeout=0.6)
        for _ in range(5):
            time.sleep(0.3)
            srv.touch()
        self.assertTrue(t.is_alive())
        t.join(3)


class TestActivatedHTTPServer(unittest.TestCase):
    def test_fd_is_duplicated_not_leaked(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen()
        srv = ActivatedHTTPServer(DummyHandler, fd=s.fileno())
        self.assertNotEqual(srv.socket.fileno(), s.fileno())
        self.assertEqual(srv.server_address, s.getsockname())
        srv.server_close()
        s.getsockname()  # caller's socket is still usable
        s.close()

    def test_unix_socket(self):
        path = os.path.join(tempfile.mkdtemp(), "sock")
        s = socket.socket(socket.AF_UNIX)
        s.bind(path)
        s.listen()
        srv = ActivatedHTTPServer(DummyHandler, sock=s)
        srv.timeout = 2
        t = threading.Thread(target=srv.handle_request)
        t.start()
        c = socket.socket(socket.AF_UNIX)
        c.connect(path)
        c.sendall(b"GET / HTTP/1.0\r\n\r\n")
        data = b""
        while chunk := c.recv(4096):
            data += chunk
        c.close()
        t.join(3)
        srv.server_close()
        self.assertIn(b"200", data.split(b"\r\n")[0])
        self.assertTrue(data.endswith(b"OK"))


if __name__ == "__main__":
    unittest.main()
