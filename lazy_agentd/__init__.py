"""
lazy-agentd
Zero-Idle-RAM Systemd Socket Activation & Auto-Hibernation Engine for Local AI Daemons.
"""

try:
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("lazy-agentd")
except PackageNotFoundError:  # running from a source tree without installing
    __version__ = "0.0.0+unknown"

from .activation import listen_fds  # noqa: E402
from .proxy import LazyProxy  # noqa: E402
from .server import ActivatedHTTPServer, LazyDaemonServer  # noqa: E402

__all__ = ["LazyDaemonServer", "ActivatedHTTPServer", "LazyProxy", "listen_fds", "__version__"]
