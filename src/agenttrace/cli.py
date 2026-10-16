"""Command line: agenttrace up | proxy | proxy-http | traces | show | sessions | drift.

`up`, `proxy` and `proxy-http` RUN something. The other commands only READ the
SQLite file, so they work even when the server is not running.

Also runnable as a module (the SDK starts the proxy this way):
    python -m agenttrace.cli proxy --name X -- <server command>
"""
import argparse
import asyncio
import sys
from datetime import datetime

import uvicorn

from agenttrace import config
from agenttrace.analysis.safety import drift_report
from agenttrace.proxy.http import create_proxy_app
from agenttrace.proxy.stdio import StdioProxy
from agenttrace.server.app import create_app
from agenttrace.storage.sqlite import SQLiteStorage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agenttrace", description="Flight recorder for MCP agents")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("up", help="start the AgentTrace server")

    proxy = sub.add_parser("proxy", help="run an MCP server (stdio) behind the recording proxy")
    proxy.add_argument("--name", default="mcp-server", help="name shown in traces and sessions")
    proxy.add_argument("command", nargs=argparse.REMAINDER, help="-- <real server command>")

    http = sub.add_parser("proxy-http", help="record a remote MCP server (Streamable HTTP)")
    http.add_argument("--name", required=True, help="name shown in traces; the URL becomes /mcp/<name>")
    http.add_argument("--url", required=True, help="the real MCP server URL")
    http.add_argument("--port", type=int, default=7319, help="port of the proxy (default 7319)")

    traces = sub.add_parser("traces", help="list recent traces")
    traces.add_argument("--limit", type=int, default=20)
    traces.add_argument("--session", help="only traces of this session id (prefix is enough)")

    show = sub.add_parser("show", help="print one trace as a tree")
    show.add_argument("trace_id", help="full id or the prefix printed by `traces`")

    sub.add_parser("sessions", help="list proxy sessions (one per proxy process)")

    drift = sub.add_parser("drift", help="report tools whose description changed since first seen")
    drift.add_argument("server", nargs="?", help="MCP server name (default: all servers)")
    return parser


def format_time(ns: int) -> str:
    """Nanoseconds since 1970 -> '2026-10-13 14:05:09' (local time)."""
    return datetime.fromtimestamp(ns / 1e9).strftime("%Y-%m-%d %H:%M:%S")


# ---- commands that RUN something --------------------------------------------------------
def cmd_up(args) -> int:
    print(f"AgentTrace on http://{config.HOST}:{config.PORT}  (db: {config.DB_PATH})")
    uvicorn.run(create_app(), host=config.HOST, port=config.PORT, log_level="warning")
    return 0


def cmd_proxy(args) -> int:
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        sys.exit("usage: agenttrace proxy --name NAME -- <server command>")
    return asyncio.run(StdioProxy(command, args.name).run())


def cmd_proxy_http(args) -> int:
    print(f"AgentTrace HTTP proxy: http://127.0.0.1:{args.port}/mcp/{args.name}  ->  {args.url}", file=sys.stderr)
    uvicorn.run(create_proxy_app({args.name: args.url}), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


# ---- commands that READ the database ----------------------------------------------------
def cmd_traces(args) -> int:
    store = SQLiteStorage(config.DB_PATH)
    session_id = None
    if args.session:  # allow a prefix of the session id
        session_id = next((s["session_id"] for s in store.list_sessions(500)
                           if s["session_id"].startswith(args.session)), args.session)
    for trace in store.list_traces(limit=args.limit, session_id=session_id):
        print(f"{trace['trace_id'][:12]}  {trace['root_name']:<28} {trace['duration_ms']:>8.1f} ms  "
              f"spans={trace['span_count']:<3} tools={trace['tool_calls'] or 0:<2} "
              f"errors={trace['error_count']}  {trace['services']}")
    return 0


def cmd_show(args) -> int:
    store = SQLiteStorage(config.DB_PATH)
    full_id = store.resolve_trace_id(args.trace_id)
    spans = store.get_trace(full_id) if full_id else []
    if not spans:
        print(f"no trace starting with '{args.trace_id}'", file=sys.stderr)
        return 1
    ids = {span.span_id for span in spans}
    children: dict = {}  # parent span id -> children (a parent that is not in the trace counts as a root)
    for span in spans:
        children.setdefault(span.parent_span_id if span.parent_span_id in ids else None, []).append(span)

    def print_tree(span, depth):
        tool = span.attributes.get("gen_ai.tool.name")
        print(f"{'  ' * depth}- {span.name}  [{span.service}] {span.duration_ms:.1f} ms"
              + (f"  args={span.attributes.get('mcp.tool.arguments')}" if tool else "")
              + ("  ERROR" if span.status_code == "ERROR" else ""))
        for child in children.get(span.span_id, []):
            print_tree(child, depth + 1)

    for root in children.get(None, []):
        print_tree(root, 0)
    return 0


def cmd_sessions(args) -> int:
    for session in SQLiteStorage(config.DB_PATH).list_sessions():
        print(f"{session['session_id'][:12]}  {session['server_name'] or '?':<16} "
              f"{format_time(session['start_ns'])}  traces={session['trace_count']:<3} "
              f"tools={session['tool_calls'] or 0:<3} errors={session['error_count']}  {session['command'] or ''}")
    return 0


def cmd_drift(args) -> int:
    store = SQLiteStorage(config.DB_PATH)
    servers = [args.server] if args.server else [server["server_name"] for server in store.list_servers()]
    found = False
    for name in servers:
        for finding in drift_report(store.list_tool_snapshots(name)):
            found = True
            print(f"[{finding['severity']}] {name}: {finding['message']}  (seen {format_time(finding['seen_ns'])})")
    if not found:
        print("no drift: every server still offers the tools it first showed")
    return 0


COMMANDS = {"up": cmd_up, "proxy": cmd_proxy, "proxy-http": cmd_proxy_http, "traces": cmd_traces,
            "show": cmd_show, "sessions": cmd_sessions, "drift": cmd_drift}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
