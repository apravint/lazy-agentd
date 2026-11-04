<div align="center">

# 💤 lazy-agentd

**Zero-Idle-RAM Systemd Socket Activation & Auto-Hibernation for Local AI & MCP Daemons**

[![CI](https://github.com/apravint/lazy-agentd/actions/workflows/ci.yml/badge.svg)](https://github.com/apravint/lazy-agentd/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9%2B-green.svg)](https://www.python.org/)
[![Systemd: Native](https://img.shields.io/badge/Systemd-Socket%20Activated-orange.svg)](#how-it-works)

<p align="center">
  <b>Stop paying RAM for local AI daemons, MCP servers and vector databases you aren't using right now.</b>
</p>

</div>

---

## ⚡ The Problem

Local AI infrastructure (Ollama, embedded vector stores, FastMCP/HTTP MCP servers, voice workers) often runs 24/7. Even when no agent is using them, these daemons hold memory and open handles, and drain laptop batteries.

**`lazy-agentd` makes them on-demand:**

* systemd holds the listening socket. Nothing of yours is running, so it costs no process memory.
* The first connection starts `lazy-agentd`. In **proxy mode** it then starts your real daemon, waits until it accepts connections, and forwards the traffic. No request is lost, because connections queue in the socket while the daemon starts.
* After `--idle-timeout` seconds with no open connections and no traffic, the daemon is stopped and `lazy-agentd` exits. The OS reclaims everything they held, including GPU memory. The socket keeps listening for next time.

Wake-up latency is your daemon's own startup time. `lazy-agentd` adds only a Python interpreter start.

---

## 🏛️ How it works

```
   [client] ──► systemd socket (127.0.0.1:9090)      nothing running, 0 MB
                       │ first connection
                       ▼
               lazy-agentd (takes over the socket)
                       │ proxy mode: starts --target, waits until ready
                       ▼
               your daemon on 127.0.0.1:{port}  ◄──► traffic forwarded
                       │ --idle-timeout with no connections
                       ▼
               daemon stopped, lazy-agentd exits      back to 0 MB
```

---

## 🚀 Quickstart

### 1. Install

```bash
pip install --user git+https://github.com/apravint/lazy-agentd.git
```

(Once a release is published to PyPI: `pip install --user lazy-agentd`.)

### 2. Make any local daemon lazy (proxy mode)

`{port}` is replaced with a free port that the backend should listen on.
Clients keep talking to the public port (`-p`).

```bash
# A FastAPI / FastMCP (HTTP) app
lazy-agentd -p 9090 --target "uvicorn app:app --host 127.0.0.1 --port {port}"

# Ollama, keeping its usual port for clients
lazy-agentd -p 11434 --target "env OLLAMA_HOST=127.0.0.1:{port} ollama serve"

# A backend with a fixed port and no way to change it
lazy-agentd -p 9090 --backend-port 8000 --target "my-daemon"
```

The backend runs in its own process group. On idle it gets `SIGTERM`, then
`SIGKILL` after 10s, so worker processes it spawned are stopped too. If it
crashes, the next connection starts it again.

### 3. Install it as a systemd user service

Generate a matching `.socket` + `.service` pair for exactly these options:

```bash
lazy-agentd --generate-systemd --name ollama-lazy -p 11434 \
  --target "env OLLAMA_HOST=127.0.0.1:{port} ollama serve" \
  --output-dir ~/.config/systemd/user

systemctl --user daemon-reload
# Enable ONLY the socket, never the service:
systemctl --user enable --now ollama-lazy.socket
```

Leave out `--output-dir` to print the units instead. The `systemd/` folder
in this repo has a plain example pair for the built-in demo server.

Check it:

```bash
systemctl --user status ollama-lazy.socket   # listening, service inactive
curl http://127.0.0.1:11434/api/tags          # starts it on demand
journalctl --user -u ollama-lazy.service -f   # watch it start and, later, hibernate
```

---

## 🐍 Python SDK: wrap your own server in-process

If your server is a Python `http.server` handler, you don't need a separate
backend process:

```python
import json
import logging
from http.server import BaseHTTPRequestHandler

from lazy_agentd import LazyDaemonServer


class MyAgentHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.dumps({"result": "done"}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Uses the systemd socket if activated, otherwise binds 127.0.0.1:9090.
    server = LazyDaemonServer(handler_class=MyAgentHandler, port=9090, idle_timeout=900)
    server.serve_forever()  # returns after 15 minutes without requests
```

Requests are handled on threads. The idle timer counts from when the last
request *finished*, so a long-running request (an LLM stream, say) is never
cut off. Call `server.touch()` to count background work as activity.

`lazy_agentd.listen_fds()` is also exported if you only want a small,
dependency-free `sd_listen_fds()` for your own server.

---

## 🤔 Why not `systemd-socket-proxyd`?

systemd ships `systemd-socket-proxyd --exit-idle-time=`, which covers the
proxy half. You still have to write and wire up a second service for the
backend yourself, and getting `StopWhenUnneeded=`/`BindsTo=` right so the
backend actually stops is fiddly. `lazy-agentd` is a single command that:

* starts the backend itself and waits until it accepts connections;
* stops the backend's whole process group on idle;
* restarts a crashed backend on the next connection;
* generates the unit files for you;
* also works without systemd (`lazy-agentd -p ... --target ...` holds the port itself), which is handy for testing.

---

## 📎 Paperclip and webhook bridges

Self-hosted [Paperclip](https://github.com/paperclipai/paperclip) workers,
agent webhook bridges and similar listeners only need to run while
something is calling them:

```bash
lazy-agentd --generate-systemd --name paperclip-bridge -p 3100 \
  --target "python3 /path/to/paperclip_bridge.py --port {port}" \
  --output-dir ~/.config/systemd/user
systemctl --user daemon-reload && systemctl --user enable --now paperclip-bridge.socket
```

---

## ⚠️ Limits

* Works with anything that talks **TCP**: HTTP, SSE and streamable-HTTP MCP servers, gRPC, databases. It does **not** wrap **stdio** MCP servers, which aren't network services.
* One backend per `lazy-agentd` instance. Run one socket per daemon.
* The backend starts when a client sends its first byte, so health checks that only connect and close don't wake it. A client that connects and stays silent (server-speaks-first protocols such as MySQL or SMTP) starts it after 1s.
* An idle keep-alive connection counts as activity. Clients that hold connections open forever will keep the daemon awake.
* Linux only (systemd, process groups).

---

## 🧪 Development

```bash
pip install -e .
python -m unittest discover -s . -p 'test_*.py' -t . -v
```

The tests include real HTTP round trips, idle-timeout and in-flight-request
behaviour, proxy mode end-to-end with a real backend process, and (when
`systemd-socket-activate` is installed) real socket activation.

Releases are published to PyPI by `.github/workflows/publish.yml` when a
GitHub release is created.

---

## 📄 License

MIT License. See [LICENSE](LICENSE). Created by [Ayyappa Pravin (@apravint)](https://github.com/apravint).
