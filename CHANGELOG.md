# Changelog

## 0.2.0

### Fixed
- **The idle timer never reset.** The server exited `idle_timeout` seconds after it *started*, even under constant traffic. Activity is now tracked per request, and the server never exits while a request is in flight.
- Leaked file descriptors when taking over the systemd socket.
- The activated socket was assumed to be IPv4. The address family is now detected, so IPv6 and Unix sockets work.
- `LISTEN_PID` is now checked, and the `LISTEN_*` variables are cleared so child processes don't think they were socket-activated.
- Log output was delayed in the journal. Messages now go through `logging` to stderr (unbuffered).
- Example unit files: the `ExecStart` path now works for `pip install --user` (`%h/.local/bin`), the `[Install]` section is removed from the service (enable only the socket), and the user-unit-irrelevant `After=network.target` is dropped.

### Added
- **Proxy mode** (`--target CMD`): start any backend on the first connection, forward TCP to it, stop it (with its process group) on idle, and restart it if it crashes. Connections that close without sending anything (health checks, port scans) don't wake the backend.
- `--generate-systemd` (with `--name` and `--output-dir`) to write a matching `.socket`/`.service` pair.
- Requests are now handled on threads, so one slow request doesn't block the others.
- `--host`, `--log-level`, `--version`, and `python -m lazy_agentd`.
- `LazyProxy` and `listen_fds()` in the public API.
- Tests for idle behaviour, proxy mode, unit generation and real socket activation. CI now covers Python 3.9–3.13 and runs lint and type checks.
- A PyPI publish workflow (trusted publishing on GitHub release).

### Changed
- Requires Python 3.9+, the oldest version CI tests.
- The version is defined only in `pyproject.toml`.
- README: the documented commands now exist, the install instructions work, and unverified claims and the M8ven badge are removed.

## 0.1.0
- Initial release.
