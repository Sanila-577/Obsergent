"""'Agent smells': problems found automatically in one trace.

Pure functions over spans: no database, no network. That makes them trivial to unit-test.
"""
from collections import Counter

from agenttrace.models import Span

LOOP_THRESHOLD = 3  # same tool + same arguments this many times = probably a loop
SLOW_TOOL_MS = 5000  # an MCP call slower than this is flagged


def find_smells(spans: list[Span]) -> list[dict]:
    smells: list[dict] = []
    # The MCP calls: spans written by the proxy (or the traced client/server) for tools/call.
    tool_calls = [s for s in spans if s.attributes.get("mcp.method.name") == "tools/call"]

    # 1. Loops: identical tool calls repeated
    repeats = Counter((s.attributes.get("gen_ai.tool.name"), s.attributes.get("mcp.tool.arguments"))
                      for s in tool_calls)
    for (tool, args), n in repeats.items():
        if n >= LOOP_THRESHOLD:
            smells.append({"type": "loop", "severity": "high",
                           "message": f"{tool} was called {n} times with the same arguments {args}"})

    # 2. Tool errors (the model may have ignored them)
    for s in tool_calls:
        if s.status_code == "ERROR":
            smells.append({"type": "tool_error", "severity": "medium", "span_id": s.span_id,
                           "message": f"{s.attributes.get('gen_ai.tool.name')} failed: {s.status_message}"})

    # 3. Slow MCP calls
    for s in tool_calls:
        if s.duration_ms > SLOW_TOOL_MS:
            smells.append({"type": "slow_tool", "severity": "low", "span_id": s.span_id,
                           "message": f"{s.attributes.get('gen_ai.tool.name')} took {s.duration_ms:.0f} ms"})
    return smells
