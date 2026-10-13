"""MCP safety checks on recorded traffic.

  * description drift  - a tool changed its description/inputs after we first saw it ("rug pull")
  * prompt injection   - instruction-like text hiding in tool descriptions or results
  * risky tools        - tool names that suggest they can change or send data
All plain functions over dicts/strings, easy to unit-test.
"""
import hashlib
import json
import re

INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"ignore (all )?(previous|prior|above) instructions",
        r"you are now",
        r"do not (tell|inform) the user",
        r"<\s*(system|important)\s*>",
        r"send .* to (http|https)://",
    )
]
RISKY_TOOL_WORDS = ("delete", "remove", "drop", "write", "exec", "shell", "send", "transfer", "pay")


def tool_fingerprints(tools: list[dict]) -> dict[str, str]:
    """A short hash of each tool's description + input schema, keyed by tool name."""
    return {t["name"]: hashlib.sha256(json.dumps(
        [t.get("description", ""), t.get("inputSchema", {})], sort_keys=True).encode()).hexdigest()[:16]
        for t in tools}


def description_drift(before: list[dict], after: list[dict]) -> list[dict]:
    """Tools whose description or schema changed since they were first seen ('rug pull')."""
    old, new = tool_fingerprints(before), tool_fingerprints(after)
    return [{"type": "tool_changed", "severity": "high", "tool": name,
             "message": f"Tool '{name}' changed its description or inputs after it was first seen"}
            for name in new if name in old and new[name] != old[name]]


def tool_set_changes(before: list[dict], after: list[dict]) -> list[dict]:
    """Tools that appeared or disappeared between two snapshots of the same server."""
    old, new = {t["name"] for t in before}, {t["name"] for t in after}
    return ([{"type": "tool_added", "severity": "medium", "tool": n,
              "message": f"Tool '{n}' was added after the first snapshot"} for n in sorted(new - old)]
            + [{"type": "tool_removed", "severity": "low", "tool": n,
                "message": f"Tool '{n}' is no longer offered"} for n in sorted(old - new)])


def drift_report(snapshots: list[dict]) -> list[dict]:
    """Compare every later snapshot of one server with the FIRST one (the baseline)."""
    if len(snapshots) < 2:
        return []
    baseline = snapshots[0]["tools"]
    findings = []
    for snap in snapshots[1:]:
        for f in description_drift(baseline, snap["tools"]) + tool_set_changes(baseline, snap["tools"]):
            findings.append(f | {"snapshot_id": snap["id"], "seen_ns": snap["first_seen_ns"]})
    return findings


def injection_findings(text: str, where: str) -> list[dict]:
    return [{"type": "prompt_injection", "severity": "high", "where": where,
             "message": f"Suspicious instruction-like text in {where}: '{m.group(0)}'"}
            for p in INJECTION_PATTERNS if (m := p.search(text or ""))]


def risky_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "risky_tool", "severity": "medium", "tool": t["name"],
             "message": f"Tool '{t['name']}' looks like it can change or send data"}
            for t in tools if any(w in t["name"].lower() for w in RISKY_TOOL_WORDS)]
