"""MCP servers and their tools, as the MCPs page shows them (pure functions over dicts the storage already returns).

For every server: how it is reached (a program on this machine, or a web address), whether a gateway sits in front of it, the
tools it offers (description, parameters in plain words, how often each was used, whether it looks risky) and whether
its tool list changed since it was first seen.
"""
# How long a call takes: typical and slow values.
from obsergent.analysis.safety import RISKY_TOOL_WORDS, drift_report
from obsergent.analysis.stats import latency_summary


def transport_of(command: str | None) -> str:
    """'web' when the proxy forwards to a web address (the command is recorded as 'http:host/path'), else 'program'."""
    return "web" if (command or "").startswith("http:") else "program"


def parameters_of(schema: dict | None) -> list[dict]:
    """A tool's input schema as a flat list: [{name, type, required, description}] (nested objects stay one entry)."""
    schema = schema or {}
    required = set(schema.get("required") or [])
    parameters = []
    for name, spec in (schema.get("properties") or {}).items():
        spec = spec if isinstance(spec, dict) else {}
        kind = spec.get("type") or ("choice" if spec.get("enum") else "any")
        parameters.append({"name": name, "type": kind if isinstance(kind, str) else "/".join(kind),
                           "required": name in required, "description": spec.get("description", ""),
                           "choices": spec.get("enum") or []})
    return parameters


def looks_risky(name: str) -> bool:
    """Same rule as the findings: the name suggests the tool can change or send data."""
    return any(word in name.lower() for word in RISKY_TOOL_WORDS)


def build_mcps(snapshots: dict[str, list[dict]], calls: list[dict], sessions: list[dict]) -> list[dict]:
    """One entry per MCP server. `snapshots`: server -> its tool-list history (oldest first); `calls`: every tool call."""
    by_tool: dict[tuple, list[dict]] = {}
    by_server: dict[str, list[dict]] = {}
    for call in calls:
        by_tool.setdefault((call["server"], call["tool"]), []).append(call)
        by_server.setdefault(call["server"], []).append(call)
    command_of = {}
    for session in sorted(sessions, key=lambda s: s["start_ns"]):
        if session.get("server_name"):
            command_of[session["server_name"]] = session.get("command")
    servers = []
    for name in sorted(set(snapshots) | {server for server in by_server if server}):
        history = snapshots.get(name, [])
        latest = history[-1]["tools"] if history else []
        drift = drift_report(history)
        server_calls = by_server.get(name, [])
        tools = []
        offered = {tool["name"] for tool in latest}
        for tool in latest:
            used = by_tool.get((name, tool["name"]), [])
            durations = [c["duration_ms"] for c in used]
            tools.append({
                "name": tool["name"], "description": tool.get("description", ""),
                "parameters": parameters_of(tool.get("inputSchema")), "schema": tool.get("inputSchema", {}),
                "risky": looks_risky(tool["name"]), "calls": len(used), "errors": sum(c["status_code"] == "ERROR" for c in used),
                "last_used_ns": max((c["start_ns"] for c in used), default=None), "used": bool(used),
                "changed": any(d.get("tool") == tool["name"] and d["type"] == "tool_changed" for d in drift),
                "decisions": sorted({c["decision"] for c in used if c["decision"]})} | latency_summary(durations))
        # Tools that were called but are not in the latest list (removed afterwards).
        for (server, tool_name), used in by_tool.items():
            if server == name and tool_name not in offered:
                tools.append({"name": tool_name, "description": "", "parameters": [], "schema": {},
                              "risky": looks_risky(tool_name or ""),
                              "calls": len(used), "errors": sum(c["status_code"] == "ERROR" for c in used),
                              "last_used_ns": max(c["start_ns"] for c in used), "used": True, "changed": False,
                              "decisions": sorted({c["decision"] for c in used if c["decision"]}), "removed": True}
                             | latency_summary([c["duration_ms"] for c in used]))
        servers.append({
            "name": name, "transport": transport_of(command_of.get(name)), "command": command_of.get(name),
            "via_gateway": any(c["decision"] is not None for c in server_calls), "tools": tools,
            "tool_count": len(latest), "calls": len(server_calls),
            "errors": sum(c["status_code"] == "ERROR" for c in server_calls),
            "error_rate": (sum(c["status_code"] == "ERROR" for c in server_calls) / len(server_calls)) if server_calls else 0,
            "last_seen_ns": max((c["start_ns"] for c in server_calls), default=history[-1]["first_seen_ns"] if history else None),
            "versions": len(history), "changes": len(drift), "changed": bool(drift)})
    return servers
