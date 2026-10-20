<div align="center">

# 💤 lazy-agentd

**Zero-Idle-RAM Systemd Socket Activation & Auto-Hibernation Engine for Local AI & MCP Daemons**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.8+](https://img.shields.io/badge/Python-3.8%2B-green.svg)](https://www.python.org/)
[![Systemd: Native](https://img.shields.io/badge/Systemd-Socket%20Activated-orange.svg)](#architecture)

<p align="center">
  <b>Stop wasting 4GB–16GB of resident memory on dormant local AI daemons, MCP servers, and vector databases.</b>
</p>

</div>

---

## ⚡ The Problem

Local AI infrastructure (Ollama proxies, embedded Qdrant vector retrieval, FastMCP servers, voice dubbing workers) often runs 24/7 in the background. Even when you aren't actively using an agent, these daemons hold memory, maintain open handles, and drain laptop batteries.

**`lazy-agentd` implements zero-idle socket activation:**
* Systemd listens on the socket with **0% CPU and 0MB resident RAM**.
* The moment a client requests `http://127.0.0.1:9090`, systemd spawns the daemon in **<120ms** via socket passing (`LISTEN_FDS`).
* After 15 minutes of inactivity (`--idle-timeout 900`), the process exits cleanly, freeing all RAM and GPU context!

---

## 🏛️ Architecture

```
                                  [Client Request]
                          (Waybar / Agent Prompt / REST)
                                         │
                                         ▼
                     ┌───────────────────────────────────────┐
                     │       systemd Socket Listener         │
                     │         (127.0.0.1:9090)              │
                     │   Consumes 0MB RAM / 0% CPU at Idle   │
                     └───────────────────┬───────────────────┘
                                         │
                         (Packet Arrives: Instant Wakeup)
                                         ▼
                     ┌───────────────────────────────────────┐
                     │          lazy-agentd Process          │
                     │       Takes over socket (FD 3)        │
                     │          Processes Requests           │
                     └───────────────────┬───────────────────┘
                                         │
                        (15 Minutes of Inactivity / Dormancy)
                                         ▼
                     ┌───────────────────────────────────────┐
                     │        Clean Process Shutdown         │
                     │      Frees all Python / GPU Memory    │
                     │        Socket Remains Listening       │
                     └───────────────────────────────────────┘
```

---

## 🚀 Quickstart

### 1. Installation

```bash
pip install lazy-agentd
```

### 2. Standalone CLI Usage

```bash
# Run standalone with a 15-minute idle timeout
lazy-agentd -p 9090 --idle-timeout 900
```

### 3. Deploying as a Systemd User Service

Copy the unit files into `~/.config/systemd/user/`:
```bash
mkdir -p ~/.config/systemd/user
cp systemd/lazy-agentd.* ~/.config/systemd/user/
systemctl --user daemon-reload

# Enable ONLY the socket (not the service!)
systemctl --user enable --now lazy-agentd.socket
```

Verify that the socket is listening with **zero resident memory**:
```bash
systemctl --user status lazy-agentd.socket
```

Now query the endpoint:
```bash
curl http://127.0.0.1:9090/
```
Systemd will instantly launch `lazy-agentd.service` to process the request!

---

## 🐍 Python SDK: Wrap Your Own AI Server

```python
from lazy_agentd import LazyDaemonServer
from http.server import BaseHTTPRequestHandler
import json

class MyAgentHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Your custom local LLM or MCP logic
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"result": "done"}).encode("utf-8"))

if __name__ == "__main__":
    # Automatically inherits systemd socket if available, or binds to 9090
    server = LazyDaemonServer(
        handler_class=MyAgentHandler,
        port=9090,
        idle_timeout=900  # Exits after 15m idle
    )
    server.serve_forever()
```

---

## 🧪 Testing

```bash
python -m unittest discover -s tests
```

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details. Created by [Ayyappa Pravin (@apravint)](https://github.com/apravint).
