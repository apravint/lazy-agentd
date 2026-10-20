import unittest
import socket
from http.server import BaseHTTPRequestHandler
from lazy_agentd.server import ActivatedHTTPServer, LazyDaemonServer

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

class TestServer(unittest.TestCase):
    def test_direct_bind_server(self):
        # Bind to random ephemeral port
        srv = LazyDaemonServer(handler_class=DummyHandler, port=0, idle_timeout=1)
        self.assertIsNotNone(srv.httpd)
        srv.httpd.server_close()

    def test_activated_server_fd(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        s.listen(1)
        fd = s.fileno()

        srv = ActivatedHTTPServer(DummyHandler, fd=fd)
        self.assertIsNotNone(srv.socket)
        srv.server_close()
        s.close()

if __name__ == "__main__":
    unittest.main()
