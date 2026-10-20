"""
Lazy-Agentd CLI
"""

import sys
import json
import argparse
from http.server import BaseHTTPRequestHandler
from .server import LazyDaemonServer

DEFAULT_STATUS = {
    "status": "Ready",
    "engine": "lazy-agentd",
    "version": "0.1.0"
}

class DemoAgentHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(DEFAULT_STATUS).encode("utf-8"))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "received", "bytes": len(body)}).encode("utf-8"))

    def log_message(self, format, *args):
        pass

def main():
    parser = argparse.ArgumentParser(
        prog="lazy-agentd",
        description="Zero-Idle-RAM Systemd Socket Activation & Auto-Hibernation Engine for Local AI Daemons"
    )
    parser.add_argument("-p", "--port", type=int, default=9090, help="Port to bind if direct (default: 9090)")
    parser.add_argument("--idle-timeout", type=int, default=900, help="Idle seconds before exit to conserve RAM (default: 900)")
    args = parser.parse_args()

    server = LazyDaemonServer(
        handler_class=DemoAgentHandler,
        port=args.port,
        idle_timeout=args.idle_timeout
    )
    server.serve_forever()

if __name__ == "__main__":
    main()
