"""
lazy-agentd
Zero-Idle-RAM Systemd Socket Activation & Auto-Hibernation Engine for Local AI Daemons.
"""

from .server import LazyDaemonServer, ActivatedHTTPServer

__version__ = "0.1.0"
__all__ = ["LazyDaemonServer", "ActivatedHTTPServer"]
