"""Command line: agenttrace up | proxy | proxy-http | traces | show | sessions | drift.

`up`, `proxy` and `proxy-http` RUN something. The other commands only READ the
SQLite file, so they work even when the server is not running.
"""
import argparse
import asyncio
import sys
from datetime import datetime

from agenttrace import config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agenttrace", description="Flight recorder for MCP agents")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("up", help="start the AgentTrace server")

    p = sub.add_parser("proxy", help="run an MCP server (stdio) behind the recording proxy")
    p.add_argument("--name", default="mcp-server", help="name shown in traces and sessions")
    p.add_argument("command", nargs=argparse.REMAINDER, help="-- <real server command>")

    h = sub.add_parser("proxy-http", help="record a remote MCP server (Streamable HTTP)")
    h.add_argument("--name", required=True, help="name shown in traces; the URL becomes /mcp/<name>")
    h.add_argument("--url", required=True, help="the real MCP server URL")
    h.add_argument("--port", type=int, default=7319, help="port of the proxy (default 7319)")

    t = sub.add_parser("traces", help="list recent traces")
    t.add_argument("--limit", type=int, default=20)
    t.add_argument("--session", help="only traces of this session id (prefix is enough)")

    s = sub.add_parser("show", help="print one trace as a tree")
    s.add_argument("trace_id", help="full id or the prefix printed by `traces`")

    sub.add_parser("sessions", help="list proxy sessions (one per proxy process)")

    d = sub.add_parser("drift", help="report tools whose description changed since first seen")
    d.add_argument("server", nargs="?", help="MCP server name (default: all servers)")
    return parser


def ts(ns: int) -> str:
    """Nanoseconds since 1970 -> '2026-10-13 14:05:09' (local time)."""
    return datetime.fromtimestamp(ns / 1e9).strftime("%Y-%m-%d %H:%M:%S")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # ---- commands that run something -------------------------------------------------
    if args.cmd == "up":
        import uvicorn

        from agenttrace.server.app import create_app
        print(f"AgentTrace on http://{config.HOST}:{config.PORT}  (db: {config.DB_PATH})")
        uvicorn.run(create_app(), host=config.HOST, port=config.PORT, log_level="warning")
        return 0
    if args.cmd == "proxy":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command:
            parser.error("usage: agenttrace proxy --name NAME -- <server command>")
        from agenttrace.proxy.stdio import StdioProxy
        return asyncio.run(StdioProxy(command, args.name).run())
    if args.cmd == "proxy-http":
        import uvicorn

        from agenttrace.proxy.http import create_proxy_app
        print(f"AgentTrace HTTP proxy: http://127.0.0.1:{args.port}/mcp/{args.name}  ->  {args.url}",
              file=sys.stderr)
        uvicorn.run(create_proxy_app({args.name: args.url}), host="127.0.0.1", port=args.port, log_level="warning")
        return 0

    # ---- commands that read the database ---------------------------------------------
    from agenttrace.analysis.safety import drift_report
    from agenttrace.storage.sqlite import SQLiteStorage
    store = SQLiteStorage(config.DB_PATH)

    if args.cmd == "traces":
        session_id = None
        if args.session:  # allow a prefix of the session id
            session_id = next((s["session_id"] for s in store.list_sessions(500)
                               if s["session_id"].startswith(args.session)), args.session)
        for tr in store.list_traces(limit=args.limit, session_id=session_id):
            print(f"{tr['trace_id'][:12]}  {tr['root_name']:<28} {tr['duration_ms']:>8.1f} ms  "
                  f"spans={tr['span_count']:<3} tools={tr['tool_calls'] or 0:<2} errors={tr['error_count']}  "
                  f"{tr['services']}")
        return 0

    if args.cmd == "show":
        full_id = store.resolve_trace_id(args.trace_id)
        spans = store.get_trace(full_id) if full_id else []
        if not spans:
            print(f"no trace starting with '{args.trace_id}'", file=sys.stderr)
            return 1
        ids = {s.span_id for s in spans}
        kids: dict = {}  # parent span id -> children (a parent that is not in the trace counts as a root)
        for sp in spans:
            kids.setdefault(sp.parent_span_id if sp.parent_span_id in ids else None, []).append(sp)

        def walk(sp, depth):
            tool = sp.attributes.get("gen_ai.tool.name")
            print(f"{'  ' * depth}- {sp.name}  [{sp.service}] {sp.duration_ms:.1f} ms"
                  + (f"  args={sp.attributes.get('mcp.tool.arguments')}" if tool else "")
                  + ("  ERROR" if sp.status_code == "ERROR" else ""))
            for child in kids.get(sp.span_id, []):
                walk(child, depth + 1)

        for root in kids.get(None, []):
            walk(root, 0)
        return 0

    if args.cmd == "sessions":
        for s in store.list_sessions():
            print(f"{s['session_id'][:12]}  {s['server_name'] or '?':<16} {ts(s['start_ns'])}  "
                  f"traces={s['trace_count']:<3} tools={s['tool_calls'] or 0:<3} errors={s['error_count']}  "
                  f"{s['command'] or ''}")
        return 0

    if args.cmd == "drift":
        servers = [args.server] if args.server else [s["server_name"] for s in store.list_servers()]
        found = False
        for name in servers:
            findings = drift_report(store.list_tool_snapshots(name))
            for f in findings:
                found = True
                print(f"[{f['severity']}] {name}: {f['message']}  (seen {ts(f['seen_ns'])})")
        if not found:
            print("no drift: every server still offers the tools it first showed")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
