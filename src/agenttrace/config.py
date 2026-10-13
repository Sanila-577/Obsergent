"""Settings, read from environment variables with sensible local defaults.

Every other module imports its settings from here, so there is exactly one
place to look when you wonder "where does the port / database path come from?".
"""
import os
from pathlib import Path

# Folder for AgentTrace's own files. Override with AGENTTRACE_HOME.
HOME = Path(os.environ.get("AGENTTRACE_HOME", Path.home() / ".agenttrace"))
# The SQLite database file (local mode).
DB_PATH = Path(os.environ.get("AGENTTRACE_DB", HOME / "agenttrace.db"))
# Where `agenttrace up` listens. 127.0.0.1 = this machine only (local-first, nothing is exposed).
HOST = os.environ.get("AGENTTRACE_HOST", "127.0.0.1")
PORT = int(os.environ.get("AGENTTRACE_PORT", "7318"))
# Where the SDK and the proxies SEND their spans (the AgentTrace server's address).
ENDPOINT = os.environ.get("AGENTTRACE_ENDPOINT", f"http://{HOST}:{PORT}")
# Longest text stored in one span attribute (arguments, results...). Bigger values are cut.
MAX_ATTR_CHARS = int(os.environ.get("AGENTTRACE_MAX_ATTR_CHARS", "4000"))
