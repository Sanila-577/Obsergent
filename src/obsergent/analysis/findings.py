"""Findings: things worth a human's attention, gathered from everything Obsergent has recorded.

Each finding has a stable id (a hash of what it is about), so a dismissed finding stays dismissed
when the list is rebuilt. Kinds:
    tool_changed / tool_added / tool_removed   a server's tool list drifted from its first snapshot
    risky_tool                                 a tool whose name suggests it can change or send data
    prompt_injection                           instruction-like text in a tool description or a tool result
    loop / tool_error / slow_tool              "agent smells" found in a run
    gateway_decision                           calls the gateway refused (unauthorized / forbidden / throttled / denied)
    token_budget / heavy_question              today's tokens near or over the budget; a question far above the usual

Pure functions: the caller (the API) reads the data, this module only decides what is a finding.
"""
# hashlib: stable ids.
import hashlib

# Drift, injection and risky-tool checks.
from obsergent.analysis.safety import drift_report, injection_findings, risky_tools

# Loop / error / slow checks.
from obsergent.analysis.smells import find_smells

# The shared data shape.
from obsergent.models import Span

# Lower number = shown first.
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
# Gateway decisions that count as findings.
REFUSED = ("unauthorized", "forbidden", "throttled", "denied")  # gateway decisions that are findings


# Stable id: same subject gives the same id, so a dismissed finding stays dismissed.
def finding_id(*parts) -> str:
    """A short stable id for a finding (same subject -> same id, so acknowledgements survive rebuilds)."""
    # Hash the parts into 12 hex characters.
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


# Build one finding dictionary.
def make(kind: str, severity: str, message: str, seen_ns: int, subject: tuple, **extra) -> dict:
    # The common fields every finding has.
    return {"id": finding_id(kind, *subject), "type": kind, "severity": severity, "message": message,
            "seen_ns": seen_ns, "count": 1, **extra}


# Findings from tool lists (drift, risky tools, injected descriptions).
def tool_list_findings(snapshots_by_server: dict[str, list[dict]]) -> list[dict]:
    """Drift between snapshots, risky tools and injection-like descriptions in the newest tool list."""
    # Collected findings.
    found = []
    # Per server...
    for server, snapshots in snapshots_by_server.items():
        # ...changes compared to the first snapshot.
        for drift in drift_report(snapshots):
            # One finding per change.
            found.append(make(drift["type"], drift["severity"], f"{server}: {drift['message']}", drift["seen_ns"],
                              (server, drift["tool"], drift["snapshot_id"]), server=server, tool=drift["tool"]))
        # No snapshots: nothing more to check.
        if not snapshots:
            # Nothing more for this span.
            continue
        # The newest tool list.
        latest = snapshots[-1]
        # Risky tool names.
        for risky in risky_tools(latest["tools"]):
            # One finding each.
            found.append(make("risky_tool", risky["severity"], f"{server}: {risky['message']}", latest["first_seen_ns"],
                              (server, risky["tool"]), server=server, tool=risky["tool"]))
        # Check each description...
        for tool in latest["tools"]:
            # ...for injection-like text.
            for hit in injection_findings(tool.get("description", ""), f"the description of '{tool['name']}'"):
                # One finding each.
                found.append(make("prompt_injection", hit["severity"], f"{server}: {hit['message']}",
                                  latest["first_seen_ns"], (server, tool["name"], hit["message"]),
                                  server=server, tool=tool["name"]))
    # All tool-list findings.
    return found


# Findings from tool results.
def result_findings(calls: list[Span]) -> list[dict]:
    """Injection-like text inside recorded tool results."""
    # Collected findings.
    found = []
    # Each recorded tool call...
    for span in calls:
        # ...its stored result text.
        text = span.attributes.get("mcp.result", "")
        # Scan it for injection-like text.
        for hit in injection_findings(text, f"the result of '{span.attributes.get('gen_ai.tool.name')}'"):
            # One finding per match (linked to the span).
            found.append(make("prompt_injection", hit["severity"], hit["message"], span.start_ns,
                              (span.span_id, hit["message"]), trace_id=span.trace_id, span_id=span.span_id,
                              server=span.attributes.get("mcp.server.name"),
                              tool=span.attributes.get("gen_ai.tool.name")))
    # All result findings.
    return found


# Findings from agent smells.
def smell_findings(traces: list[list[Span]]) -> list[dict]:
    """Loops, ignored tool errors and slow tools in each run."""
    # Collected findings.
    found = []
    # Each run...
    for spans in traces:
        # ...each problem found.
        for smell in find_smells(spans):
            # When the run started.
            started = min(s.start_ns for s in spans)
            # One finding per smell.
            found.append(make(smell["type"], smell["severity"], smell["message"], started,
                              (spans[0].trace_id, smell["type"], smell["message"]), trace_id=spans[0].trace_id,
                              span_id=smell.get("span_id")))
    # All smell findings.
    return found


# Findings from refused gateway calls, grouped.
def gateway_findings(calls: list[Span]) -> list[dict]:
    """Calls the gateway refused, grouped by (decision, tool, caller): one finding with a count.

    `calls` mixes the agent-side spans (they know the tool and the caller) and the gateway's own spans (they
    also cover callers that never went through Obsergent's proxy). A call seen from both sides is counted once.
    """
    # One finding per (decision, tool, caller).
    groups: dict[tuple, dict] = {}
    # Gateway calls already counted (a call seen from both sides is counted once).
    seen_activities: set[str] = set()
    # Agent-side spans first, so they provide tool and caller names.
    for span in sorted(calls, key=lambda s: s.attributes.get("obsergent.layer") == "gateway"):  # agent side first
        # What the gateway decided.
        decision = span.attributes.get("gateway.decision")
        # The correlation id of the call.
        activity = span.attributes.get("gateway.activity_id")
        # Skip allowed calls and calls already counted.
        if decision not in REFUSED or (activity and activity in seen_activities):
            continue
        # Remember this call.
        if activity:
            seen_activities.add(activity)
        # Best available name for what was called.
        tool = span.attributes.get("gen_ai.tool.name") or span.attributes.get("gateway.api") or span.name
        # Shortcut.
        attrs = span.attributes
        # Best available name for who called.
        caller = (attrs.get("obsergent.caller.application") or attrs.get("obsergent.caller.client_id")
                  or attrs.get("gateway.consumer_key") or "an anonymous caller")
        # Group key.
        key = (decision, tool, caller)
        # Already have this group: just count it.
        if key in groups:
            # One more occurrence.
            groups[key]["count"] += 1
            # Remember the latest time.
            groups[key]["seen_ns"] = max(groups[key]["seen_ns"], span.start_ns)
            continue
        # Denied/forbidden is more serious than throttled/unauthorized.
        severity = "medium" if decision in ("forbidden", "denied") else "low"
        # Create the group's finding.
        groups[key] = make("gateway_decision", severity, f"'{tool}' was {decision} by the gateway for {caller}",
                           span.start_ns, key, tool=tool, decision=decision, trace_id=span.trace_id,
                           span_id=span.span_id, server=span.attributes.get("mcp.server.name"))
    # Add "(N times)" to repeated findings.
    for group in groups.values():
        # Only when repeated.
        if group["count"] > 1:
            # Append the count.
            group["message"] += f" ({group['count']} times)"
    # All gateway findings.
    return list(groups.values())


# Mark dismissed findings and sort.
def order_findings(findings: list[dict], acknowledged: dict[str, int]) -> list[dict]:
    """Mark dismissed findings and sort: severity first, newest first within a severity."""
    # Each finding...
    for finding in findings:
        # ...is dismissed if its id is in the acknowledged list.
        finding["acknowledged"] = finding["id"] in acknowledged
        # ...and when it was dismissed.
        finding["acknowledged_ns"] = acknowledged.get(finding["id"])
    # Severity first, then newest first.
    return sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f["severity"], 3), -f["seen_ns"]))


# Findings about token usage (the budget of config.yaml and unusually heavy questions).
def usage_findings(budget: dict, heavy: list[dict], now_ns: int) -> list[dict]:
    """A finding when today's tokens reach the warning share of the budget, and one per heavy question."""
    found = []
    if budget.get("enabled") and budget["level"] in ("warn", "over"):
        severity = "high" if budget["level"] == "over" else "medium"
        found.append(make("token_budget", severity, f"Today's tokens are at {budget['share']:.0%} of your daily budget "
                          f"({budget['used']:,} of {budget['budget']:,})", now_ns,
                          ("budget", time_day(now_ns), budget["level"])))
    for question in heavy:
        usual = f", {question['times_usual']:.0f}x the usual" if question.get("times_usual") else ""
        found.append(make("heavy_question", "low", f"A question used {question['tokens']:,} tokens{usual}: "
                          f"\"{question['question'][:80]}\"", question["started_ns"], (question["trace_id"],),
                          trace_id=question["trace_id"]))
    return found


# The day of a moment, so the budget finding is a new one each day.
def time_day(ns: int) -> int:
    return ns // (24 * 3600 * 1_000_000_000)
