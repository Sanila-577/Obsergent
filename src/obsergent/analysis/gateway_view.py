"""The gateway panel's data: what the gateway did with each call, and where the time went.

Two recorders see the same call from different sides:
    agent side    the Obsergent proxy span (`tools/call search_books`): the time the agent waited
    gateway side  the gateway's own spans (Envoy router and policy engine): total time at the gateway and a breakdown by phase
                  (key validation, throttling, mediation, backend, ...)
They are matched by trace (APIM continues the proxy's `traceparent`, so they share a trace) or, failing
that, by the gateway's activity id (the `activityid` response header). Anything unmatched is shown as such,
never guessed.
"""
# Counter counts decisions; defaultdict creates missing entries automatically.
from collections import Counter, defaultdict

# p50/p95 summaries.
from obsergent.analysis.stats import latency_summary

# The shared data shape.
from obsergent.models import Span


# Time spent in each gateway phase below one call span.
def phases_of(call: Span, children: dict[str, list[Span]]) -> dict[str, float]:
    """Milliseconds spent in each phase below one gateway call span (summed if a phase repeats)."""
    # phase name -> milliseconds.
    totals: dict[str, float] = defaultdict(float)
    # A to-do list of spans to visit (start with the call's children).
    pending = list(children.get(call.span_id, []))
    # Visit spans until none are left (walks the whole subtree).
    while pending:
        # Take one.
        span = pending.pop()
        # It is a phase span: add its time.
        if "gateway.phase" in span.attributes:
            # Add the phase latency (summed if the phase repeats).
            totals[span.attributes["gateway.phase"]] += span.attributes.get("gateway.latency_ms", span.duration_ms)
        # Also visit its children.
        pending.extend(children.get(span.span_id, []))
    # Plain dict result.
    return dict(totals)


# Build the whole Gateway page payload.
def summarize_gateway(gateway_spans: list[Span], proxy_spans: list[Span], limit: int = 50) -> dict:
    """`gateway_spans`: spans of the gateway layer. `proxy_spans`: agent-side spans with a gateway outcome."""
    # parent span id -> child spans.
    children: dict[str, list[Span]] = defaultdict(list)
    # Fill the parent->children map.
    for span in gateway_spans:
        # Roots have no parent.
        if span.parent_span_id:
            # Register under its parent.
            children[span.parent_span_id].append(span)
    # The spans that cover a whole call (they carry an activity id), newest first.
    gateway_calls = sorted((s for s in gateway_spans if "gateway.activity_id" in s.attributes),
                           key=lambda s: -s.start_ns)
    # Agent-side spans indexed by activity id, to match them.
    proxy_by_activity = {s.attributes["gateway.activity_id"]: s for s in proxy_spans
                         if "gateway.activity_id" in s.attributes}
    # The API Platform gateway has no correlation header, but it continues the proxy's trace: the proxy span
    # is the PARENT of the gateway's call span.
    proxy_by_id = {s.span_id: s for s in proxy_spans}

    # Result list, durations per phase, and decision counts.
    calls, phase_durations, decisions = [], defaultdict(list), Counter()
    # Describe each gateway call.
    for call in gateway_calls:
        # Its phase breakdown.
        phases = phases_of(call, children)
        # Collect durations per phase for the statistics.
        for phase, ms in phases.items():
            phase_durations[phase].append(ms)
        # allowed/denied/... as classified at ingest.
        decision = call.attributes.get("gateway.decision", "unknown")
        # The matching agent-side span, if any.
        proxy = proxy_by_id.get(call.parent_span_id) or proxy_by_activity.get(call.attributes["gateway.activity_id"])
        # The gateway's own span only knows the HTTP status (a refused tool call is just "400"); the proxy saw the
        # JSON-RPC body too, so when it has a more specific verdict (denied) use that.
        if decision == "error" and proxy and proxy.attributes.get("gateway.decision") not in (None, "allowed"):
            decision = proxy.attributes["gateway.decision"]
        # Count it.
        decisions[decision] += 1
        # One row for the table.
        calls.append({
            "activity_id": call.attributes["gateway.activity_id"], "trace_id": call.trace_id,
            "span_id": call.span_id, "start_ns": call.start_ns, "api": call.attributes.get("gateway.api"),
            "status": call.attributes.get("gateway.status"), "decision": decision,
            "consumer_key": call.attributes.get("gateway.consumer_key"), "gateway_ms": call.duration_ms,
            "phases": phases,
            # the agent-side view of the same call, when it was recorded
            "proxy_span_id": proxy.span_id if proxy else None,
            "tool": proxy.attributes.get("gen_ai.tool.name") if proxy else None,
            "method": proxy.attributes.get("mcp.method.name") if proxy else None,
            "proxy_ms": proxy.duration_ms if proxy else None,
            "caller": (proxy.attributes.get("obsergent.caller.application")
                       or proxy.attributes.get("obsergent.caller.client_id")) if proxy else None,
            "correlation": ("trace" if proxy and proxy.trace_id == call.trace_id else "activity") if proxy else "none",
        })

    # Decision counts per tool.
    by_tool: dict[str, Counter] = defaultdict(Counter)
    # Decision counts per caller.
    by_caller: dict[str, Counter] = defaultdict(Counter)
    # Fill both breakdowns.
    for entry in calls:
        by_tool[entry["tool"] or entry["method"] or "(not matched)"][entry["decision"]] += 1
        by_caller[entry["caller"] or entry["consumer_key"] or "(unknown)"][entry["decision"]] += 1
    # The final payload.
    return {
        "receiving": bool(gateway_spans),  # is gateway telemetry arriving at all?
        "last_seen_ns": max((s.end_ns for s in gateway_spans), default=None),
        "calls_total": len(calls),
        "decisions": dict(decisions),
        "phases": {phase: latency_summary(values) for phase, values in sorted(phase_durations.items())},
        "by_tool": {tool: dict(counts) for tool, counts in sorted(by_tool.items())},
        "by_caller": {caller: dict(counts) for caller, counts in sorted(by_caller.items())},
        "calls": calls[:limit],
    }
