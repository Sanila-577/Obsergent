"""What happens to spans after they are parsed: store them, and learn from them.

    OTLP body --parse--> [Span] --ingest_spans--+--> spans table
                                                +--> tool_snapshots (one per new tools/list result)

Kept separate from server/app.py so the same steps can be reused (tests, a future
queue worker in server mode) without a web server.
"""
import json

from agenttrace.models import Span
from agenttrace.storage.base import Backend


def tool_lists(spans: list[Span]) -> list[tuple[str, list[dict], int]]:
    """Find tools/list results among the spans: [(server name, tools, time)]."""
    found = []
    for s in spans:
        raw = s.attributes.get("mcp.tools")  # written by proxy/recorder.py on a tools/list response
        if not raw:
            continue
        try:
            tools = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue  # truncated or not JSON: skip rather than store garbage
        if isinstance(tools, list):
            # Prefer the proxy's name for the server; fall back to the service name.
            server = str(s.attributes.get("mcp.server.name") or s.service)
            found.append((server, tools, s.end_ns))
    return found


def ingest_spans(spans: list[Span], backend: Backend) -> dict:
    """Save spans and remember any new version of an MCP server's tool list."""
    backend.save_spans(spans)
    new_snapshots = [server for server, tools, seen_ns in tool_lists(spans)
                     if backend.save_tool_snapshot(server, tools, seen_ns)]
    return {"spans": len(spans), "new_tool_snapshots": new_snapshots}
