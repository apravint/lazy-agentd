"""
Lazy-Agentd CLI
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler
from typing import List, Optional

from . import __version__
from .server import LazyDaemonServer
from .systemd_units import render_units

log = logging.getLogger("lazy_agentd")


class DemoAgentHandler(BaseHTTPRequestHandler):
    def _json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._json({"status": "Ready", "engine": "lazy-agentd", "version": __version__})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self._json({"status": "received", "bytes": len(body)})

    def log_message(self, format: str, *args: object) -> None:
        log.debug("%s - %s", self.address_string(), format % args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lazy-agentd",
        description=(
            "Zero-idle-RAM systemd socket activation for local AI and MCP daemons. "
            "With --target, starts that command on the first connection, proxies "
            "to it, and stops it after --idle-timeout seconds without traffic."
        ),
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--host", default="127.0.0.1", help="address to bind when not socket-activated (default: 127.0.0.1)")
    p.add_argument(
        "-p", "--port", type=int, default=9090,
        help="port to bind when not socket-activated (default: 9090)",
    )
    p.add_argument(
        "--idle-timeout", type=float, default=900,
        help="seconds without traffic before exiting; 0 disables (default: 900)",
    )
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    proxy = p.add_argument_group("proxy mode")
    proxy.add_argument(
        "--target", metavar="CMD",
        help='backend command to start on demand, e.g. "uvicorn app:app --port {port}"',
    )
    proxy.add_argument(
        "--backend-port", type=int,
        help="port the backend listens on (default: a free port substituted into {port})",
    )
    proxy.add_argument("--backend-host", default="127.0.0.1", help="host the backend listens on (default: 127.0.0.1)")
    proxy.add_argument(
        "--startup-timeout", type=float, default=60,
        help="seconds to wait for the backend to accept connections (default: 60)",
    )

    gen = p.add_argument_group("systemd unit generation")
    gen.add_argument(
        "--generate-systemd", action="store_true",
        help="print (or write) a .socket/.service pair for these options and exit",
    )
    gen.add_argument("--name", default="lazy-agentd", help="unit name for --generate-systemd (default: lazy-agentd)")
    gen.add_argument("--output-dir", help="write the units here instead of printing them, e.g. ~/.config/systemd/user")
    return p


def _service_argv(args: argparse.Namespace) -> List[str]:
    argv = [sys.executable, "-m", "lazy_agentd", "--host", args.host, "--port", str(args.port),
            "--idle-timeout", f"{args.idle_timeout:g}"]
    if args.target:
        argv += ["--target", args.target, "--backend-host", args.backend_host,
                 "--startup-timeout", f"{args.startup_timeout:g}"]
        if args.backend_port is not None:
            argv += ["--backend-port", str(args.backend_port)]
    return argv


def _generate(args: argparse.Namespace) -> int:
    units = render_units(args.name, args.host, args.port, _service_argv(args))
    if not args.output_dir:
        for filename, text in units.items():
            print(f"# ---- {filename} ----\n{text}")
        return 0
    out = os.path.expanduser(args.output_dir)
    os.makedirs(out, exist_ok=True)
    for filename, text in units.items():
        path = os.path.join(out, filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {path}")
    print(f"\nnext: systemctl --user daemon-reload && systemctl --user enable --now {args.name}.socket")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="[lazy-agentd] %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    if args.generate_systemd:
        return _generate(args)

    if args.target:
        from .proxy import LazyProxy

        try:
            proxy = LazyProxy(
                args.target,
                backend_port=args.backend_port,
                backend_host=args.backend_host,
                listen_host=args.host,
                listen_port=args.port,
                idle_timeout=args.idle_timeout,
                startup_timeout=args.startup_timeout,
            )
        except ValueError as exc:
            parser.error(str(exc))
        return proxy.run()

    LazyDaemonServer(
        handler_class=DemoAgentHandler,
        port=args.port,
        host=args.host,
        idle_timeout=args.idle_timeout,
    ).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
