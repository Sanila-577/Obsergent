"""What happens to spans after they are parsed: store them, and learn from them.

    OTLP body --parse--> [Span] --ingest_spans--+--> spans table (gateway spans normalized first)
                                                +--> tool_snapshots (one per new tools/list result)

Kept separate from server/app.py so the same steps can be reused (tests, a future
queue worker in server mode) without a web server.
"""
# json parses the stored tool list.
import json

# Gateway span normalization, the Span shape and the database interface.
from agenttrace.ingest.billed import add_billing_attributes
from agenttrace.ingest.gateway import normalize_gateway_spans
from agenttrace.models import Span
from agenttrace.storage.base import Backend


def tool_lists(spans: list[Span]) -> list[tuple[str, list[dict], int]]:
    """Find tools/list results among the spans: [(server name, tools, time)]."""
    # Collected results.
    found = []
    for s in spans:
        raw = s.attributes.get("mcp.tools")  # written by proxy/recorder.py on a tools/list response
        # Most spans have no tool list.
        if not raw:
            continue
        try:
            # The proxy stored the tool list as JSON text.
            tools = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue  # truncated or not JSON: skip rather than store garbage
        # It must be a list of tool definitions.
        if isinstance(tools, list):
            # Prefer the proxy's name for the server; fall back to the service name.
            server = str(s.attributes.get("mcp.server.name") or s.service)
            found.append((server, tools, s.end_ns))
    # [(server, tools, time)]
    return found


def ingest_spans(spans: list[Span], backend: Backend) -> dict:
    """Save spans and remember any new version of an MCP server's tool list."""
    add_billing_attributes(spans)  # the provider's own cost and billing facts, dug out of the recorded response
    normalize_gateway_spans(spans)  # API Manager's own spans get AgentTrace's attribute names first
    # Store the spans.
    backend.save_spans(spans)
    # Remember each tool list; the list collects servers whose list is NEW (so drift can be flagged).
    new_snapshots = [server for server, tools, seen_ns in tool_lists(spans)
                     if backend.save_tool_snapshot(server, tools, seen_ns)]
    # Counts reported back to the sender.
    return {"spans": len(spans), "new_tool_snapshots": new_snapshots}
