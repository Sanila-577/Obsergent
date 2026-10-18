"""Command line: agenttrace up | proxy | proxy-http | traces | show | sessions | drift.

`up`, `proxy` and `proxy-http` RUN something. The other commands only READ the
SQLite file, so they work even when the server is not running.

Also runnable as a module (the SDK starts the proxy this way):
    python -m agenttrace.cli proxy --name X -- <server command>
"""
# argparse reads the words typed after `agenttrace` (sub-command and --options).
import argparse

# asyncio runs the stdio proxy (it does two things at once).
import asyncio

# sys: exit codes and stderr.
import sys

# datetime formats timestamps for printing.
from datetime import datetime

# uvicorn is the web server program that runs FastAPI apps.
import uvicorn

# Settings (ports, database path).
from agenttrace import config

# Drift detection used by `agenttrace drift`.
from agenttrace.analysis.safety import drift_report

# Builds the HTTP proxy web app.
from agenttrace.proxy.http import create_proxy_app

# The stdio proxy class.
from agenttrace.proxy.stdio import StdioProxy

# Builds the AgentTrace server web app.
from agenttrace.server.app import create_app

# Starts the optional gRPC receiver.
from agenttrace.server.grpc_receiver import start_grpc_server

# The database.
from agenttrace.storage.sqlite import SQLiteStorage


# Describe every command and option the CLI accepts.
def build_parser() -> argparse.ArgumentParser:
    # The top-level parser: `agenttrace <command> ...`.
    parser = argparse.ArgumentParser(prog="agenttrace", description="Flight recorder for MCP agents")
    # Each command (up, proxy, ...) is a "sub-parser"; one is required.
    sub = parser.add_subparsers(dest="cmd", required=True)
    # Command `up`: start the server.
    up = sub.add_parser("up", help="start the AgentTrace server")
    # Flag: also open the gRPC port (store_true = present means True).
    up.add_argument("--grpc", action="store_true",
                    help=f"also accept OTLP over gRPC on port {config.grpc_port()} "
                         "(needs `uv pip install agenttrace[grpc]`; the WSO2 gateway exports its traces this way)")

    # Command `proxy`: run a stdio MCP server through the recorder.
    proxy = sub.add_parser("proxy", help="run an MCP server (stdio) behind the recording proxy")
    # Label shown in the UI.
    proxy.add_argument("--name", default="mcp-server", help="name shown in traces and sessions")
    # Everything after `--` is the real server command (REMAINDER = take all the rest).
    proxy.add_argument("command", nargs=argparse.REMAINDER, help="-- <real server command>")

    # Command `proxy-http`: record a remote MCP server.
    http = sub.add_parser("proxy-http", help="record a remote MCP server (Streamable HTTP)")
    # The label; the proxy URL ends with it. Default: gateway.mcp_name in config.yaml.
    http.add_argument("--name", default=None,
                      help="name shown in traces, the URL ends /mcp/<name> (config.yaml: gateway.mcp_name)")
    # The real server URL. Default: the MCP server at the gateway, from config.yaml.
    http.add_argument("--url", default=None, help="the real MCP server URL (default: the gateway's, from config.yaml)")
    # Local port of the proxy. Default: proxy.port in config.yaml.
    http.add_argument("--port", type=int, default=None, help="port of the proxy (config.yaml: proxy.port)")
    # Trust this certificate file (for a gateway with its own cert).
    http.add_argument("--ca-bundle", help="CA certificate file to trust for the upstream (e.g. a gateway's own cert)")
    # Skip certificate checks (dev only).
    http.add_argument("--insecure", action="store_true",
                      help="do NOT check the upstream's TLS certificate (local development only)")

    # Command `config`: print the settings in use (the Makefile reads ports from here).
    cfg = sub.add_parser("config", help="show the settings (config.yaml + environment), or one value")
    cfg.add_argument("key", nargs="?", help="a dotted key such as server.port; omit to show everything")

    # Command `traces`: print recent runs.
    traces = sub.add_parser("traces", help="list recent traces")
    # How many to print.
    traces.add_argument("--limit", type=int, default=20)
    # Only runs of one session.
    traces.add_argument("--session", help="only traces of this session id (prefix is enough)")

    # Command `show`: print one run as a tree.
    show = sub.add_parser("show", help="print one trace as a tree")
    # Which run (an id prefix is enough).
    show.add_argument("trace_id", help="full id or the prefix printed by `traces`")

    # Command `sessions`: list proxy sessions.
    sub.add_parser("sessions", help="list proxy sessions (one per proxy process)")

    # Command `drift`: show changed tool descriptions.
    drift = sub.add_parser("drift", help="report tools whose description changed since first seen")
    # Optional server name (nargs="?" = zero or one).
    drift.add_argument("server", nargs="?", help="MCP server name (default: all servers)")
    # Hand the finished parser back.
    return parser


# Make a timestamp readable.
def format_time(ns: int) -> str:
    """Nanoseconds since 1970 -> '2026-10-13 14:05:09' (local time)."""
    return datetime.fromtimestamp(ns / 1e9).strftime("%Y-%m-%d %H:%M:%S")


# ---- commands that RUN something --------------------------------------------------------
def cmd_up(args) -> int:
    # Open (and create/upgrade) the database; shared by HTTP and gRPC.
    storage = SQLiteStorage(config.db_path())  # shared by the HTTP API and (optionally) the gRPC receiver
    # Tell the user where to open the UI.
    print(f"AgentTrace on http://{config.host()}:{config.port()}  (db: {config.db_path()})")
    # Only if --grpc was given: start the gRPC receiver in background threads.
    if args.grpc:
        # Start it; we only need the port it bound.
        _, grpc_port = start_grpc_server(storage, config.host(), config.grpc_port())
        print(f"OTLP/gRPC receiver on {config.host()}:{grpc_port}")
    # Start the web server; this call blocks until Ctrl+C.
    uvicorn.run(create_app(storage), host=config.host(), port=config.port(), log_level="warning")
    return 0


# `agenttrace proxy`: run a stdio MCP server through the recorder.
def cmd_proxy(args) -> int:
    # Drop the leading `--` separator.
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    # No server command given: print usage and stop.
    if not command:
        sys.exit("usage: agenttrace proxy --name NAME -- <server command>")
    # Run the async proxy to completion; its exit code becomes ours.
    return asyncio.run(StdioProxy(command, args.name).run())


# `agenttrace proxy-http`: record a remote server.
def cmd_proxy_http(args) -> int:
    # Fill what was not typed from config.yaml.
    name = args.name or config.mcp_name()
    url = args.url or config.gateway_mcp_url()
    port = args.port or config.proxy_port()
    # Tell the user what URL to point their client at (stderr keeps stdout clean).
    print(f"AgentTrace HTTP proxy: http://{config.proxy_host()}:{port}/mcp/{name}  ->  {url}", file=sys.stderr)
    # TLS check: off (--insecure), a certificate file (--ca-bundle) or the system default.
    verify = False if args.insecure else (args.ca_bundle or True)  # False | path | default system certificates
    # Loud warning when TLS checks are off.
    if args.insecure:
        print("WARNING: TLS verification is OFF for the upstream (development only)", file=sys.stderr)
    # Build the proxy web app for the single named upstream.
    app = create_proxy_app({name: url}, verify=verify)
    # Serve it on localhost.
    uvicorn.run(app, host=config.proxy_host(), port=port, log_level="warning")
    return 0


# `agenttrace config [key]`: print the settings in use.
def cmd_config(args) -> int:
    if args.key:
        # One value, e.g. `agenttrace config server.port` -> 7318 (the environment overrides config.yaml).
        value = config.get(args.key)
        if value is None:
            sys.exit(f"unknown setting '{args.key}'")
        print(value)
        return 0
    # Everything, grouped as in config.yaml, with the file that was read.
    print(f"# file: {config.config_file() or '(none: built-in defaults)'}")
    for section, values in config.load().items():
        for name in values:
            print(f"{section}.{name} = {config.get(f'{section}.{name}')}")
    return 0


# ---- commands that READ the database ----------------------------------------------------
def cmd_traces(args) -> int:
    # Open the database file (works while the server is stopped).
    store = SQLiteStorage(config.db_path())
    # The optional session filter.
    session_id = None
    # Allow a shortened session id.
    if args.session:  # allow a prefix of the session id
        session_id = next((s["session_id"] for s in store.list_sessions(500)
                           if s["session_id"].startswith(args.session)), args.session)
    # One printed line per run: id, root step, duration, counts, services, model.
    for trace in store.list_traces(limit=args.limit, session_id=session_id):
        print(f"{trace['trace_id'][:12]}  {trace['root_name']:<28} {trace['duration_ms']:>8.1f} ms  "
              f"spans={trace['span_count']:<3} tools={trace['tool_calls'] or 0:<2} "
              f"errors={trace['error_count']}  {trace['services']}"
              + (f"  model={trace['models']} tokens={trace['total_tokens']}" if trace["models"] else ""))
    return 0


# `agenttrace show <id>`: print a run's spans as an indented tree.
def cmd_show(args) -> int:
    store = SQLiteStorage(config.db_path())
    # Expand the short id.
    full_id = store.resolve_trace_id(args.trace_id)
    # Load its spans.
    spans = store.get_trace(full_id) if full_id else []
    # Nothing found: error on stderr, exit code 1.
    if not spans:
        print(f"no trace starting with '{args.trace_id}'", file=sys.stderr)
        return 1
    # All span ids present in this run.
    ids = {span.span_id for span in spans}
    # parent id -> its children (a parent that is not in the trace counts as a root).
    children: dict = {}  # parent span id -> children (a parent that is not in the trace counts as a root)
    # Group spans under their parents.
    for span in spans:
        children.setdefault(span.parent_span_id if span.parent_span_id in ids else None, []).append(span)

    # Print one span, then its children one level deeper (recursion).
    def print_tree(span, depth):
        # Tool name, if this is a tool call.
        tool = span.attributes.get("gen_ai.tool.name")
        # Model name, if this is a model call.
        model = span.attributes.get("llm.model_name")
        # One line: indentation, name, service, duration, extras.
        print(f"{'  ' * depth}- {span.name}  [{span.service}] {span.duration_ms:.1f} ms"
              + (f"  args={span.attributes.get('mcp.tool.arguments')}" if tool else "")
              + (f"  model={model} tokens={span.attributes.get('llm.token_count.total')}" if model else "")
              + ("  ERROR" if span.status_code == "ERROR" else ""))
        # Recurse into the children.
        for child in children.get(span.span_id, []):
            print_tree(child, depth + 1)

    # Start from the roots (spans without a parent).
    for root in children.get(None, []):
        print_tree(root, 0)
    return 0


# `agenttrace sessions`: one line per proxy session.
def cmd_sessions(args) -> int:
    for session in SQLiteStorage(config.db_path()).list_sessions():
        print(f"{session['session_id'][:12]}  {session['server_name'] or '?':<16} "
              f"{format_time(session['start_ns'])}  traces={session['trace_count']:<3} "
              f"tools={session['tool_calls'] or 0:<3} errors={session['error_count']}  {session['command'] or ''}")
    return 0


# `agenttrace drift`: compare each server's tool list with the first one seen.
def cmd_drift(args) -> int:
    store = SQLiteStorage(config.db_path())
    # One named server, or all known servers.
    servers = [args.server] if args.server else [server["server_name"] for server in store.list_servers()]
    # Remember whether anything was printed.
    found = False
    # For every server...
    for name in servers:
        # ...print each change found.
        for finding in drift_report(store.list_tool_snapshots(name)):
            found = True
            print(f"[{finding['severity']}] {name}: {finding['message']}  (seen {format_time(finding['seen_ns'])})")
    # Reassure the user when nothing changed.
    if not found:
        print("no drift: every server still offers the tools it first showed")
    return 0


# Command name -> function that runs it.
COMMANDS = {"up": cmd_up, "proxy": cmd_proxy, "proxy-http": cmd_proxy_http, "traces": cmd_traces,
            "config": cmd_config, "show": cmd_show, "sessions": cmd_sessions, "drift": cmd_drift}


# The entry point: `agenttrace` on the command line calls this (see pyproject.toml).
def main(argv: list[str] | None = None) -> int:
    # Parse what the user typed.
    args = build_parser().parse_args(argv)
    # Run the chosen command; its return value is the exit code.
    return COMMANDS[args.cmd](args)


# Also allows `python -m agenttrace.cli ...` (the SDK starts the proxy that way).
if __name__ == "__main__":
    sys.exit(main())
