"""
Render a matching ``.socket`` + ``.service`` pair for systemd user units.
"""

from __future__ import annotations

import shlex
from typing import Dict, Sequence


def _exec_quote(argv: Sequence[str]) -> str:
    # systemd accepts shell-style quoting, but expands % specifiers and $VARs.
    line = " ".join(shlex.quote(a) for a in argv)
    return line.replace("%", "%%").replace("$", "$$")


def _listen_stream(host: str, port: int) -> str:
    if ":" in host:  # IPv6 literal
        return f"[{host}]:{port}"
    return f"{host}:{port}"


def render_units(
    name: str,
    host: str,
    port: int,
    exec_argv: Sequence[str],
    description: str = "lazy-agentd on-demand daemon",
) -> Dict[str, str]:
    """Return ``{"<name>.socket": ..., "<name>.service": ...}``.

    Only the socket has an ``[Install]`` section: enable the socket, never
    the service, so the service starts on the first connection.
    """
    socket_unit = f"""\
[Unit]
Description={description} (socket)

[Socket]
ListenStream={_listen_stream(host, port)}
Accept=no

[Install]
WantedBy=sockets.target
"""
    service_unit = f"""\
[Unit]
Description={description}
Requires={name}.socket
After={name}.socket

[Service]
Type=simple
ExecStart={_exec_quote(exec_argv)}
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=3
"""
    return {f"{name}.socket": socket_unit, f"{name}.service": service_unit}
