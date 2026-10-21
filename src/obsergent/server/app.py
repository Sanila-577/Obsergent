"""The Obsergent server: receives OTLP spans, serves the REST API and the web UI.

    SDK / proxy / gateway ──POST /v1/traces──► parse (ingest/otlp.py) ──► save (storage) ──► SQLite
    web UI / CLI / curl   ──GET  /api/...  ──► read (storage) + analysis (smells, drift, findings...)
    browser               ──GET  /         ──► the built React UI (server/static/), if it has been built

Run with `obsergent up` (cli.py). Everything the UI shows comes from the endpoints below; the UI has no
logic of its own that the API does not expose, so the CLI and scripts can do the same things.
"""
# gzip: OTLP exporters may compress their request bodies.
import gzip

# time: current time for "last N hours" windows.
import time

# Counter counts things; defaultdict is a dict that creates missing entries.
from collections import Counter, defaultdict

# asdict turns a Span object into a plain dict (JSON-friendly).
from dataclasses import asdict

# Path: file locations (where the built UI lives).
from pathlib import Path

# FastAPI is the web framework; Query/Request/Response/HTTPException handle input and output.
from fastapi import FastAPI, HTTPException, Query, Request, Response

# FileResponse sends a file; StaticFiles serves a whole folder of files.
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# DecodeError is raised when a protobuf body is corrupted.
from google.protobuf.message import DecodeError

# The empty OTLP "success" reply message.
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse

# config: host, port, database path.
from obsergent import config

# Compare two runs (first step where they differ).
from obsergent.analysis.diff import first_divergence, tool_steps

# Build the "Findings" list from different sources and order it.
from obsergent.analysis.findings import (
    gateway_findings,
    order_findings,
    result_findings,
    smell_findings,
    tool_list_findings,
    usage_findings,
)

# Summaries for the Gateway page.
from obsergent.analysis.gateway_view import summarize_gateway

# Model calls and chat reconstruction.
from obsergent.analysis.generations import (
    build_conversation,
    find_generations,
    summarize_generations,
)

# Suggest an MCP access-control policy.
from obsergent.analysis.policy import suggest_policy
from obsergent.analysis.queries import build_thread, summarize_query
from obsergent.analysis.queries import timeline as query_timeline

# Detect tool-description changes (drift).
from obsergent.analysis.safety import drift_report

# Detect bad agent behaviour (loops, ignored errors...).
from obsergent.analysis.smells import find_smells

# p50/p95 latency summaries.
from obsergent.analysis.stats import latency_summary

# Text diff between two tool lists.
from obsergent.analysis.toolsdiff import diff_tool_lists
from obsergent.analysis.usage import change, heavy_questions

# Convert incoming OTLP bodies to Span objects.
from obsergent.ingest.otlp import parse_export_json, parse_export_request

# Save spans and remember tool lists.
from obsergent.ingest.pipeline import ingest_spans
from obsergent.server import catalog, price_sync
from obsergent.server.costing import CostCalculator, first_question, price_status, spending, trace_cost

# The database interface type.
from obsergent.storage.base import Backend

# The SQLite implementation.
from obsergent.storage.sqlite import SQLiteStorage

# The built React UI is copied here (ui/ -> npm run build).
STATIC_DIR = Path(__file__).parent / "static"  # the built UI is copied here (ui/ -> npm run build)
# Nanoseconds in one hour (spans use nanosecond timestamps).
NS_PER_HOUR = 3600 * 1_000_000_000
# Dashboards look at the last 24 hours unless told otherwise.
DEFAULT_WINDOW_HOURS = 24
# URL prefixes that belong to the API, so the UI fallback must not answer them.
NOT_API = ("api/", "v1/", "health")  # paths the UI fallback must never answer


# Build and return the web app. Tests call this with their own temporary database.
def create_app(storage: Backend | None = None) -> FastAPI:
    # One object plays both roles (spans + metadata). Tests pass in a temporary database.
    store = storage or SQLiteStorage(config.db_path())
    # The web app object; every @app.get/post below registers a URL on it.
    app = FastAPI(title="Obsergent", version="0.2.0")

    # Turn "last N hours" into an absolute start timestamp.
    def window_start(hours: float | None) -> int | None:
        """Nanosecond timestamp `hours` ago (None = no limit)."""
        return time.time_ns() - int(hours * NS_PER_HOUR) if hours else None

    # Convert Unix seconds (what the browser sends) to nanoseconds.
    def seconds_to_ns(seconds: float | None) -> int | None:
        return int(seconds * 1_000_000_000) if seconds is not None else None

    # Load the spans of a run; accepts a shortened id; 404 if it does not exist.
    def spans_of(trace_id: str):
        """All spans of a trace (id prefix allowed) or a 404."""
        # Expand a short id to the full id (or keep what was typed).
        full_id = store.resolve_trace_id(trace_id) or trace_id
        spans = store.get_trace(full_id)
        if not spans:
            raise HTTPException(404, "trace not found")
        return full_id, spans

    # Count the gateway's decisions (allowed, denied...) in a time window.
    def gateway_decisions(since: int | None, calls: list[dict]) -> dict:
        """What the gateway decided, per call. The gateway's own spans cover every call it saw (even from callers
        that never used Obsergent's proxy); without gateway telemetry, fall back to what the proxy observed."""
        # Spans written by APIM's telemetry.
        gateway_calls = store.find_spans("gateway.activity_id", layer="gateway", since_ns=since, limit=20000)
        # Prefer the gateway's own verdicts; fall back to what the proxy saw.
        decisions = [s.attributes.get("gateway.decision") for s in gateway_calls] or [c["decision"] for c in calls]
        return dict(Counter(d for d in decisions if d))

    # Collect every finding from all sources, then mark the dismissed ones.
    def all_findings(hours: float | None = None) -> list[dict]:
        """Every finding currently true, from tool lists, recent results, recent runs and gateway decisions."""
        # Where the time window starts.
        since = window_start(hours)
        # Tool-list history of every server (for drift checks).
        snapshots = {server["server_name"]: store.list_tool_snapshots(server["server_name"])
                     for server in store.list_servers()}
        # Recent tool calls (to scan results for injection-like text).
        recent_calls = store.find_spans("mcp.method.name", "tools/call", layer="agent", since_ns=since, limit=500)
        # Recent runs (to scan for agent smells).
        recent_traces = store.list_traces(limit=100, since_ns=since)
        # Spans on both sides that carry a gateway decision.
        gateway_calls = store.find_spans("gateway.decision", since_ns=since, limit=2000)  # both sides of each call
        # Join the four sources into one list.
        # Token usage: today's budget and questions far above the usual.
        calculator = CostCalculator(store)
        cards = catalog.question_summaries(store, calculator, 500, since_ns=since)
        heavy = heavy_questions(cards, config.usage_question_token_alert())
        found = (tool_list_findings(snapshots) + result_findings(recent_calls)
                 + smell_findings([store.get_trace(t["trace_id"]) for t in recent_traces])
                 + gateway_findings(gateway_calls) + usage_findings(catalog.budget(store, calculator), heavy, time.time_ns()))
        calculator.finish()
        # Sort by severity and attach the "acknowledged" flag.
        return order_findings(found, store.list_acknowledged())

    # ----------------------------------------------------------------- ingest
    @app.post("/v1/traces")
    # Handle one OTLP export request.
    async def receive_otlp(request: Request) -> Response:
        """Standard OTLP/HTTP endpoint - point any OpenTelemetry exporter here.

        Accepts protobuf (what the Python exporters send) and JSON (what some
        collectors and curl-based tools send).
        """
        # Which format the sender used (protobuf or JSON).
        content_type = request.headers.get("content-type", "")
        # The raw request bytes.
        body = await request.body()
        # Undo gzip compression if used.
        if request.headers.get("content-encoding") == "gzip":  # exporters may compress
            body = gzip.decompress(body)
        # Parse by format; any parse failure becomes HTTP 400.
        try:
            if "protobuf" in content_type:
                # Binary protobuf -> Spans.
                spans = parse_export_request(body)
            elif "json" in content_type:
                # JSON -> Spans.
                spans = parse_export_json(body)
            else:
                # Unsupported format.
                raise HTTPException(415, "Send OTLP as application/x-protobuf or application/json")
        # Bad bytes, bad JSON or bad hex ids.
        except (DecodeError, ValueError) as err:  # bad bytes / bad JSON / bad hex ids
            raise HTTPException(400, f"Could not parse the OTLP request: {err}") from err
        # Normalize gateway spans, save them, remember tool lists.
        ingest_spans(spans, store)
        # The reply uses the same format as the request (an empty "success" message).
        if "json" in content_type:
            return Response("{}", media_type="application/json")
        # Empty protobuf success message.
        return Response(ExportTraceServiceResponse().SerializeToString(), media_type="application/x-protobuf")

    # ------------------------------------------------------------------- runs
    @app.get("/api/traces")
    # Every parameter is an optional filter taken from the URL's query string.
    def list_traces(limit: int = Query(50, ge=1, le=500), service: str | None = None, session_id: str | None = None,
                    model: str | None = None, errors_only: bool = False, tool: str | None = None,
                    server: str | None = None, q: str | None = None, decision: str | None = None,
                    since: float | None = None, until: float | None = None, before_ns: int | None = None):
        """Runs, newest first. Filters: service, session, model, errors, tool, server, free text, gateway
        decision, a time range (`since`/`until` in Unix seconds) and `before_ns` to page to older runs."""
        # Ask the database for the matching runs.
        traces = store.list_traces(
            limit=limit, service=service, session_id=session_id, model=model, errors_only=errors_only, tool=tool,
            server=server, query=q, decision=decision, since_ns=seconds_to_ns(since), until_ns=seconds_to_ns(until),
            before_ns=before_ns)
        # Attach the number of automatic findings to each run.
        calculator = CostCalculator(store)
        for trace in traces:  # a count of automatic findings, the question asked and the cost of each run
            spans = store.get_trace(trace["trace_id"])
            trace["smells_count"] = len(find_smells(spans))
            trace["question"] = first_question(find_generations(spans))
            trace["cost"] = trace_cost(calculator, spans)
        calculator.finish()
        return traces

    # ONE RUN: all of its spans plus detected smells.
    @app.get("/api/traces/{trace_id}")
    # Fetch the run's spans.
    def get_trace(trace_id: str):
        full_id, spans = spans_of(trace_id)
        # Spans converted to dicts (with duration) so FastAPI can send them as JSON.
        calculator = CostCalculator(store)
        answer = {"trace_id": full_id,
                  "spans": [asdict(s) | {"duration_ms": s.duration_ms} for s in spans],
                  "smells": find_smells(spans), "question": first_question(find_generations(spans)),
                  "cost": trace_cost(calculator, spans)}
        calculator.finish()
        return answer

    # MODEL CALLS of a run.
    @app.get("/api/traces/{trace_id}/generations")
    def get_generations(trace_id: str, reprice: str | None = None):
        """Every model call of the run: messages, tokens, latency, and the MCP call each requested tool led to."""
        full_id, spans = spans_of(trace_id)
        # Pull model-call records out of the spans.
        generations = find_generations(spans)
        calculator = CostCalculator(store, reprice)
        cost = calculator.attach(generations)  # the cost of each call, and the total
        calculator.finish()
        return {"trace_id": full_id, "summary": summarize_generations(generations) | {"cost": cost},
                "generations": [asdict(g) | {"latency_ms": g.latency_ms} for g in generations]}

    # The run as a chat.
    @app.get("/api/traces/{trace_id}/conversation")
    def get_conversation(trace_id: str):
        """The run as a chat (system, user, assistant, tool); tool calls link to the real MCP call."""
        full_id, spans = spans_of(trace_id)
        generations = find_generations(spans)
        calculator = CostCalculator(store)
        cost = calculator.attach(generations)
        calculator.finish()
        return {"trace_id": full_id, "summary": summarize_generations(generations) | {"cost": cost},
                "messages": build_conversation(generations)}

    # COMPARE two runs.
    @app.get("/api/diff")
    def diff_runs(a: str, b: str):
        """Compare two runs: the tool calls of each, and the first step where they differ."""
        # Load both runs.
        id_a, spans_a = spans_of(a)
        id_b, spans_b = spans_of(b)
        return {"a": id_a, "b": id_b, "divergence": first_divergence(spans_a, spans_b),
                "steps_a": tool_steps(spans_a), "steps_b": tool_steps(spans_b)}

    # ----------------------------------------------------------------- models
    @app.get("/api/models")
    def list_models(hours: float | None = DEFAULT_WINDOW_HOURS, buckets: int = Query(24, ge=1, le=96)):
        """One entry per model (a dated and an undated name are the same model): usage, tokens, cost, speed, price, what
        the model can do (context window, abilities, open weights) and its token trend over the last `hours`."""
        calculator = CostCalculator(store)
        models = catalog.model_catalog(store, calculator, window_start(hours), time.time_ns(), buckets)
        calculator.finish()
        return models

    # ------------------------------------------------------------------- usage
    @app.get("/api/usage")
    def get_usage(hours: float = DEFAULT_WINDOW_HOURS, buckets: int = Query(24, ge=1, le=96)):
        """Token usage: totals, over time by model, by model/agent/question/tool, tool-description overhead, prompts close to
        the model's limit, the daily budget, heavy questions and the change from the period before."""
        calculator = CostCalculator(store)
        report = catalog.usage(store, calculator, window_start(hours), time.time_ns(), buckets)
        calculator.finish()
        return report | {"window_hours": hours}

    # ---------------------------------------------------------------- questions
    @app.get("/api/queries")
    def list_queries(hours: float | None = None, limit: int = Query(50, ge=1, le=200), before_ns: int | None = None,
                     q: str | None = None, since: float | None = None, until: float | None = None):
        """The questions people asked, newest first: question, answer, time, cost, models, tools, steps, tokens, status."""
        calculator = CostCalculator(store)
        cards = catalog.question_summaries(
            store, calculator, limit, since_ns=seconds_to_ns(since) or window_start(hours),
            until_ns=seconds_to_ns(until), before_ns=before_ns, query=q)
        calculator.finish()
        return cards

    @app.get("/api/queries/timeline")
    def queries_timeline(hours: float = DEFAULT_WINDOW_HOURS):
        """The peaks chart: one point per question (or time slots when there are many)."""
        calculator = CostCalculator(store)
        cards = catalog.question_summaries(store, calculator, 500, since_ns=window_start(hours))
        calculator.finish()
        return query_timeline(cards, hours, time.time_ns()) | {"window_hours": hours}

    @app.get("/api/queries/{trace_id}")
    def get_query(trace_id: str):
        """One question with its whole thread: the steps in order (with their tokens), each tool with its input and result."""
        full_id, spans = spans_of(trace_id)
        generations = find_generations(spans)
        calculator = CostCalculator(store)
        cost = calculator.attach(generations)
        calculator.finish()
        return summarize_query(full_id, spans, generations) | {
            "cost": cost, "thread": build_thread(spans, generations), "tools_offered": sorted(
                {name for g in generations for name in g.tools})}

    # ------------------------------------------------------------------ agents
    @app.get("/api/agents")
    def list_agents():
        """The agents (programs that asked the model): questions, models, tools, cost, framework."""
        calculator = CostCalculator(store)
        agents = [{key: value for key, value in agent.items() if key != "runs"}
                  for agent in catalog.agent_catalog(store, calculator).values()]
        calculator.finish()
        return sorted(agents, key=lambda agent: -agent["last_ns"])

    @app.get("/api/agents/{name}/graph")
    def get_agent_graph(name: str):
        """The steps of one agent as nodes and edges: step -> model, step -> tool -> MCP server -> gateway."""
        calculator = CostCalculator(store)
        graph = catalog.agent_graph(store, calculator, name)
        calculator.finish()
        if graph is None:
            raise HTTPException(404, "agent not found")
        return graph

    # -------------------------------------------------------------------- MCPs
    @app.get("/api/mcps")
    def list_mcps():
        """The MCP servers with their tools (description, parameters, usage, risk) and tool-list changes."""
        return catalog.mcp_catalog(store)

    # --------------------------------------------------------------- sessions
    @app.get("/api/sessions")
    def list_sessions(limit: int = 50):
        return store.list_sessions(limit=limit)

    # Runs belonging to one session.
    @app.get("/api/sessions/{session_id}/traces")
    def session_traces(session_id: str, limit: int = 200):
        return store.list_traces(limit=limit, session_id=session_id)

    # Session timeline.
    @app.get("/api/sessions/{session_id}/timeline")
    def session_timeline(session_id: str):
        """Every MCP request of one proxy session in order: what an external app (Claude Desktop...) did."""
        # All MCP requests of the session in order.
        spans = store.list_session_spans(session_id)
        if not spans:
            raise HTTPException(404, "session not found")
        return {"session_id": session_id, "events": [{
            "span_id": s.span_id, "trace_id": s.trace_id, "start_ns": s.start_ns, "duration_ms": s.duration_ms,
            "method": s.attributes.get("mcp.method.name"), "tool": s.attributes.get("gen_ai.tool.name"),
            "arguments": s.attributes.get("mcp.tool.arguments"), "result": s.attributes.get("mcp.result"),
            "status": s.status_code, "message": s.status_message, "decision": s.attributes.get("gateway.decision"),
            "http_status": s.attributes.get("http.response.status_code")} for s in spans]}

    # ---------------------------------------------------------- servers, tools
    @app.get("/api/servers")
    def list_servers():
        return store.list_servers()

    # Compare two servers' tool lists (gateway vs upstream).
    @app.get("/api/servers/compare")
    def compare_servers(a: str, b: str):
        """Latest tool list of server `a` against server `b` (e.g. the gateway's view vs the upstream's)."""
        # Latest tool list per server name.
        lists = {}
        for name in (a, b):
            snapshots = store.list_tool_snapshots(name)
            if not snapshots:
                raise HTTPException(404, f"no tool snapshots for '{name}'")
            lists[name] = snapshots[-1]["tools"]
        return {"a": a, "b": b} | diff_tool_lists(lists[a], lists[b])

    # Every version of a server's tool list plus a drift report.
    @app.get("/api/servers/{name}/snapshots")
    def server_snapshots(name: str):
        snapshots = store.list_tool_snapshots(name)
        if not snapshots:
            raise HTTPException(404, "no tool snapshots for that server")
        return {"server": name, "snapshots": snapshots, "drift": drift_report(snapshots)}

    # Text diff between two versions of a tool list.
    @app.get("/api/servers/{name}/diff")
    def server_diff(name: str, from_id: int | None = None, to_id: int | None = None):
        """How a server's tools changed between two snapshots (default: the first one and the latest)."""
        snapshots = store.list_tool_snapshots(name)
        if not snapshots:
            raise HTTPException(404, "no tool snapshots for that server")
        # Look snapshots up by id; default is first vs latest.
        by_id = {s["id"]: s for s in snapshots}
        before, after = by_id.get(from_id, snapshots[0]), by_id.get(to_id, snapshots[-1])
        return {"server": name, "from_id": before["id"], "to_id": after["id"]} | diff_tool_lists(
            before["tools"], after["tools"])

    # TOOLS table: per-tool statistics.
    @app.get("/api/tools")
    def list_tools(hours: float | None = DEFAULT_WINDOW_HOURS):
        """Every tool that was called: calls, errors, latency (average, p50, p95), gateway decisions, last seen."""
        # Calls grouped by (server, tool).
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for call in store.list_calls(since_ns=window_start(hours)):
            groups[(call["server"], call["tool"])].append(call)
        # One summary row per tool.
        tools = []
        for (server, tool), calls in groups.items():
            tools.append({
                "server": server, "tool": tool, "calls": len(calls),
                "errors": sum(c["status_code"] == "ERROR" for c in calls),
                "last_seen_ns": max(c["start_ns"] for c in calls),
                "decisions": dict(Counter(c["decision"] for c in calls if c["decision"])),
            } | latency_summary([c["duration_ms"] for c in calls]))
        return sorted(tools, key=lambda t: -t["calls"])

    # MAP page data: nodes and edges.
    @app.get("/api/topology")
    def topology(hours: float | None = DEFAULT_WINDOW_HOURS, expand: str = ""):
        """Who calls which MCP server: callers -> (gateway ->) servers with call and error counts. Tools are listed only for
        the servers named in `expand` (comma separated, or `*` for all), so the map stays readable."""
        expanded = {name for name in expand.split(",") if name}
        # Edges keyed by (source, target).
        edges: dict[tuple, dict] = {}

        # Add one call to an edge's counters.
        def count(source: tuple, target: tuple, call: dict) -> None:
            edge = edges.setdefault((source, target), {"source": f"{source[0]}:{source[1]}",
                                                       "target": f"{target[0]}:{target[1]}", "calls": 0, "errors": 0})
            edge["calls"] += 1
            edge["errors"] += call["status_code"] == "ERROR"

        tool_counts: dict[str, set] = defaultdict(set)
        gateway_servers = set()
        for call in store.list_calls(since_ns=window_start(hours)):
            # The caller's best available name.
            client = call["application"] or call["client_id"] or call["root_service"] or "external app"
            server, tool = call["server"] or "unknown server", call["tool"] or "?"
            tool_counts[server].add(tool)
            if call["decision"] is not None:
                # Through the gateway: caller -> gateway -> server.
                gateway_servers.add(server)
                count(("client", client), ("gateway", "gateway"), call)
                count(("gateway", "gateway"), ("server", server), call)
            else:
                count(("client", client), ("server", server), call)
            if "*" in expanded or server in expanded:
                count(("server", server), ("tool", f"{server}/{tool}"), call)
        # Build the node list from the edges' ends.
        nodes = {}
        for (source, target) in edges:
            for kind, label in (source, target):
                nodes[f"{kind}:{label}"] = {"id": f"{kind}:{label}", "kind": kind, "label": label.split("/")[-1],
                                            "via_gateway": kind == "server" and label in gateway_servers,
                                            "tool_count": len(tool_counts[label]) if kind == "server" else None,
                                            "expanded": kind == "server" and ("*" in expanded or label in expanded)}
        return {"nodes": list(nodes.values()), "edges": list(edges.values())}

    # ---------------------------------------------------------------- overview
    @app.get("/api/stats/overview")
    def overview(hours: float = DEFAULT_WINDOW_HOURS, buckets: int = Query(24, ge=1, le=96)):
        """The headline numbers and chart data for the Overview page."""
        # Window start and the current time.
        since, now = window_start(hours), time.time_ns()
        # Tool calls in the window.
        calls = store.list_calls(since_ns=since)
        # Headline totals.
        counts = store.overview_counts(since)
        # Per-tool stats, reusing the /api/tools function.
        per_tool = {t["tool"]: t for t in list_tools(hours)}
        # Five most-called tools.
        busiest = sorted(per_tool.values(), key=lambda t: -t["calls"])[:5]
        # Five tools with the worst 95th-percentile latency.
        slowest = sorted((t for t in per_tool.values() if t["p95_ms"] is not None), key=lambda t: -t["p95_ms"])[:5]
        # Findings that have not been dismissed.
        findings = [f for f in all_findings(hours) if not f["acknowledged"]]
        # The MCP servers and the tools they offer (what "Tools" on the Overview counts).
        mcps = catalog.mcp_catalog(store)
        calculator = CostCalculator(store)
        cards = catalog.question_summaries(store, calculator, 500, since_ns=since)
        # Tokens in this window, in the window before it (for "+12 %") and today's budget.
        rows = catalog.call_rows(store, calculator, since)
        before = catalog.tokens_of(catalog.call_rows(store, calculator, since - (now - since), since))
        tokens = {kind: sum(row[kind] for row in rows) for kind in ("input", "output", "cached", "reasoning")}
        tokens |= {"total": tokens["input"] + tokens["output"], "change": change(tokens["input"] + tokens["output"], before),
                   "budget": catalog.budget(store, calculator)}
        calculator.finish()
        return {
            "discussions": counts["questions"], "mcps": len(mcps), "tokens": tokens,
            "steps_total": sum(c["steps"] for c in cards), "human_messages": sum(c["human_messages"] for c in cards),
            "ai_messages": sum(c["ai_messages"] for c in cards),
            "problem_questions": sum(c["status"] == "problem" for c in cards),
            "heavy_questions": len(heavy_questions(cards, config.usage_question_token_alert())),
            "tools_total": len({t["name"] for mcp in mcps for t in mcp["tools"] if not t.get("removed")}) or len(per_tool),
            "latest_queries": cards[:6], "timeline": query_timeline(cards, hours, now),
            "window_hours": hours, "counts": counts,
            "error_rate": (counts["errors"] / counts["spans"]) if counts["spans"] else 0,
            "tool_latency": latency_summary([c["duration_ms"] for c in calls]),
            "decisions": gateway_decisions(since, calls),
            "busiest_tools": busiest, "slowest_tools": slowest,
            "activity": store.activity_series(since, now, buckets),
            "open_findings": len(findings), "open_findings_high": sum(f["severity"] == "high" for f in findings),
            "servers": len(store.list_servers()), "sessions": len(store.list_sessions(500)),
            "models": store.list_model_usage(),
            "cost": spending(store, since, now, 1, detail=False)}

    # ---------------------------------------------------------------- spending and prices
    # SPENDING page: what the model calls cost in a time window.
    @app.get("/api/spending")
    def get_spending(hours: float = DEFAULT_WINDOW_HOURS, buckets: int = Query(24, ge=1, le=96), reprice: str | None = None):
        """Cost in a window: total, by model, by tool, over time (for the stacked chart) and the most expensive runs."""
        return spending(store, window_start(hours), time.time_ns(), buckets, reprice)

    # What the "prices checked ... ago" badge and the price-check panel show.
    @app.get("/api/prices")
    def get_prices():
        return price_status(store)

    # "Check now": download the price lists again (no-op when auto refresh is off and nothing is due).
    @app.post("/api/prices/refresh")
    def refresh_prices():
        outcome = price_sync.refresh(store, force=True)
        return {"outcome": outcome} | price_status(store)

    # ---------------------------------------------------------------- findings
    @app.get("/api/findings")
    def list_findings(severity: str | None = None, type: str | None = None, include_acknowledged: bool = False,
                      hours: float | None = None):
        """Things worth a look: drift, risky tools, injection-like text, agent smells, refused gateway calls."""
        findings = all_findings(hours)
        if not include_acknowledged:
            findings = [f for f in findings if not f["acknowledged"]]
        return [f for f in findings if (not severity or f["severity"] == severity) and (not type or f["type"] == type)]

    # Dismiss a finding.
    @app.post("/api/findings/{finding_id}/ack")
    def acknowledge(finding_id: str, note: str = ""):
        store.acknowledge_finding(finding_id, note)
        return {"id": finding_id, "acknowledged": True}

    # Restore a dismissed finding.
    @app.delete("/api/findings/{finding_id}/ack")
    def unacknowledge(finding_id: str):
        store.unacknowledge_finding(finding_id)
        return {"id": finding_id, "acknowledged": False}

    # ----------------------------------------------------------------- gateway
    @app.get("/api/gateway/summary")
    def gateway_summary(hours: float | None = DEFAULT_WINDOW_HOURS, limit: int = Query(50, ge=1, le=500)):
        """What the gateway did: decisions, per-phase latency, per tool and caller, and the latest calls."""
        since = window_start(hours)
        # APIM's own spans.
        gateway_spans = store.find_spans(layer="gateway", since_ns=since, limit=20000)
        # Proxy spans that know a gateway activity id (to join both sides).
        proxy_spans = store.find_spans("gateway.decision", layer="agent", since_ns=since, limit=5000)
        return summarize_gateway(gateway_spans, proxy_spans, limit=limit)

    # One gateway call in detail.
    @app.get("/api/gateway/calls/{activity_id}")
    def gateway_call(activity_id: str):
        """One call through the gateway: its summary and every gateway span (phases) of its trace."""
        # Find spans by the correlation id.
        spans = store.find_spans("gateway.activity_id", activity_id)
        if not spans:
            raise HTTPException(404, "no gateway call with that activity id")
        # Load the whole trace that call belongs to.
        trace_spans = store.get_trace(spans[0].trace_id)
        gateway_spans = [s for s in trace_spans if s.attributes.get("obsergent.layer") == "gateway"]
        proxy_spans = [s for s in trace_spans if s.attributes.get("gateway.decision") is not None
                       and s.attributes.get("obsergent.layer") is None]
        summary = summarize_gateway(gateway_spans, proxy_spans, limit=500)
        call = next((c for c in summary["calls"] if c["activity_id"] == activity_id), None)
        return {"call": call, "spans": [asdict(s) | {"duration_ms": s.duration_ms} for s in gateway_spans]}

    # Suggest an allow-list policy for a server.
    @app.get("/api/policy/suggestion")
    def policy_suggestion(server: str):
        """A suggested MCP Access Control policy (allow-list + scopes) from the tools a server offers and uses."""
        snapshots = store.list_tool_snapshots(server)
        if not snapshots:
            raise HTTPException(404, "no tool snapshots for that server")
        # How often each tool of that server was called.
        usage = Counter(c["tool"] for c in store.list_calls() if c["server"] == server)
        return suggest_policy(server, snapshots[-1]["tools"], dict(usage))

    # Has anything new been stored? The UI asks every second and reloads its data only when the answer changes.
    @app.get("/api/version")
    def data_version():
        return {"version": store.data_version()}

    # Liveness check (used by tests and the start-up scripts).
    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ------------------------------------------------------------------ the UI
    # Registered last: anything that is not an API route gets the built UI's file or its index.html, so client-side routes
    # (/conversations, /gateway...) survive a page reload. The folder is checked on every request, not only at start-up, so a UI
    # built (or rebuilt) while the server runs is served at once.
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets", check_dir=False), name="assets")

    # Catch-all route for UI pages.
    @app.get("/{path:path}", include_in_schema=False)
    # Return a real file if it exists, else index.html (or a hint when the UI has not been built).
    def serve_ui(path: str):
        if path.startswith(NOT_API):
            raise HTTPException(404, "not found")
        if not (STATIC_DIR / "index.html").exists():
            raise HTTPException(404, "The web UI is not built yet: run `make ui-build` (the API works without it).")
        candidate = (STATIC_DIR / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(STATIC_DIR.resolve()):  # no ../ escapes
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")

    # Hand the finished app to the caller (uvicorn).
    return app
