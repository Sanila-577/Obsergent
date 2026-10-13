"""mcp_proxy.py - a generic MCP proxy that records every call with OpenTelemetry.

Put it in front of ANY stdio MCP server (Python, Node, Go - it doesn't matter):
    python mcp_proxy.py -- python bookshop_server.py
    python mcp_proxy.py -- npx -y @modelcontextprotocol/server-filesystem /tmp

How it works
  * The client starts the proxy instead of the real server.
  * The proxy starts the real server as a child process.
  * Every JSON-RPC line is copied across unchanged - except that each request
    becomes a span, and the span's trace context is written into params._meta
    so the server (if it is traced) can join the same trace.

      client ──stdin──► PROXY ──stdin──► real server
      client ◄─stdout── PROXY ◄─stdout── real server
                          │
                          └─ one span per request, saved to traces.db
"""
import asyncio  # the proxy copies two streams at the same time
import json  # MCP messages are JSON, one per line
import os  # environment variables (service name, trace parent)
import sys  # our own stdin/stdout (the client side) and command-line arguments
import time  # time.monotonic(): start time of each pending request

from opentelemetry import context, trace  # context = "which span is current"; trace = tracer API
from opentelemetry.propagate import extract, inject  # extract: dict -> context; inject: context -> dict
from opentelemetry.trace import SpanKind, Status, StatusCode  # span role + success/error marker

from tracker import setup_tracing  # Example 1: finished spans -> SQLite (path from TRACKER_DB)

MAX_ATTR_CHARS = 2000  # keep span attributes small
# If a key in the arguments/results contains one of these words, its value is hidden.
SECRET_WORDS = ("password", "token", "api_key", "secret", "authorization")

# Turn tracing on. The proxy is its own program, so it gets its own service name;
# that is how view.py tells proxy spans ("mcp-proxy") from agent spans apart.
setup_tracing(os.environ.get("PROXY_SERVICE_NAME", "mcp-proxy"))
tracer = trace.get_tracer("mcp-proxy")

# A parent for messages that carry no trace context (initialize, tools/list...).
# The agent passes its current trace in MCP_PROXY_TRACEPARENT. (We avoid the plain
# TRACEPARENT name: CI systems and other tools often set it for their own traces.)
_session_tp = os.environ.get("MCP_PROXY_TRACEPARENT")
# With the variable: a context that points at the agent's span.
# Without it (e.g. Claude Desktop): an empty context, so each request starts its own trace.
SESSION_CONTEXT = extract({"traceparent": _session_tp}) if _session_tp else context.Context()

# Requests sent to the server that have no answer yet:  request id -> (span, start time).
# A span is opened when the request goes by and closed when the matching response comes back.
pending: dict = {}


def redact(value):
    """Hide values whose key looks secret, before they are recorded."""
    if isinstance(value, dict):
        # Replace the value with *** when the key contains a secret word; otherwise look deeper.
        return {k: "***" if any(w in k.lower() for w in SECRET_WORDS) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]  # check every item of a list too
    return value  # plain value: keep as is


def short(obj) -> str:
    """Redact, turn into JSON text and cut at MAX_ATTR_CHARS."""
    text = json.dumps(redact(obj), ensure_ascii=False)
    return text if len(text) <= MAX_ATTR_CHARS else text[:MAX_ATTR_CHARS] + "...(truncated)"


def on_client_message(msg: dict) -> dict:
    """A message going client -> server. Start a span for each request."""
    # A request has both "method" and "id". Anything else (notifications such as
    # "initialized") gets no response, so there is nothing to time: forward it as is.
    if "method" not in msg or "id" not in msg:
        return msg  # a notification: just forward it
    method = msg["method"]  # e.g. "initialize", "tools/list", "tools/call"
    params = msg.setdefault("params", {}) or {}  # make sure params exists
    meta = params.setdefault("_meta", {})  # the protocol's place for extra metadata
    # Parent = the agent's tool span if the message carries a traceparent (tools/call does),
    # otherwise the session-level parent from the environment variable.
    parent = extract(meta) if "traceparent" in meta else SESSION_CONTEXT
    # What the request is about: the tool name, or the resource URI, or nothing.
    target = params.get("name") or params.get("uri") or ""
    # start_span (not start_as_current_span): we end it later, in another function, when the response arrives.
    span = tracer.start_span(f"{method} {target}".strip(), context=parent, kind=SpanKind.CLIENT)
    span.set_attribute("mcp.method.name", method)  # OpenTelemetry MCP attribute names
    span.set_attribute("jsonrpc.request.id", str(msg["id"]))
    if method == "tools/call":
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", target)  # which tool
        span.set_attribute("mcp.tool.arguments", short(params.get("arguments", {})))  # with what arguments (secrets hidden)
    elif "uri" in params:
        span.set_attribute("mcp.resource.uri", params["uri"])  # resources/read etc.
    # Overwrite _meta.traceparent with THIS span's own id: a traced server will
    # now see the proxy span as its parent. The agent's original value was already used above.
    inject(meta, context=trace.set_span_in_context(span))
    pending[msg["id"]] = (span, time.monotonic())  # remember it until the response arrives
    return msg  # forward the (slightly extended) request


def on_server_message(msg: dict) -> dict:
    """A message going server -> client. Finish the matching span."""
    # A response has an "id" plus "result" or "error", and the id matches a request we saw.
    if "id" in msg and ("result" in msg or "error" in msg) and msg["id"] in pending:
        span, _ = pending.pop(msg["id"])  # find (and forget) the span of that request
        if "error" in msg:  # protocol-level error
            span.set_status(Status(StatusCode.ERROR, msg["error"].get("message", "error")))
            span.set_attribute("mcp.error.code", msg["error"].get("code", 0))
        else:
            result = msg["result"]
            # A tool can also fail "politely": the call succeeds but result.isError is true.
            if isinstance(result, dict) and result.get("isError"):
                span.set_status(Status(StatusCode.ERROR, "tool returned isError"))
            span.set_attribute("mcp.result", short(result))  # what came back (secrets hidden)
        span.end()  # the span's duration = request seen -> response seen
    return msg  # forward the response unchanged


async def pump(reader: asyncio.StreamReader, write, handler):
    """Copy JSON lines from reader to write(), passing each through handler."""
    while line := await reader.readline():  # MCP stdio = one JSON message per line; "" means closed
        try:
            msg = handler(json.loads(line))  # parse, let the handler record it
            line = (json.dumps(msg, ensure_ascii=False) + "\n").encode()  # re-encode (may include new _meta)
        except (json.JSONDecodeError, TypeError):
            pass  # not JSON? forward it untouched
        await write(line)  # pass it on to the other side


async def main(command: list[str]) -> int:
    loop = asyncio.get_running_loop()
    # Start the REAL server as a child process, with pipes on its stdin and stdout.
    # (limit = biggest single line we accept: 16 MB, big tool results fit.)
    server = await asyncio.create_subprocess_exec(
        *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, limit=16 * 1024 * 1024
    )
    # Our own stdin is where the client talks to us; wrap it in an async reader.
    stdin_reader = asyncio.StreamReader(limit=16 * 1024 * 1024)
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(stdin_reader), sys.stdin)

    async def to_server(data: bytes):
        server.stdin.write(data)  # forward a client message to the real server
        await server.stdin.drain()

    async def to_client(data: bytes):
        sys.stdout.buffer.write(data)  # forward a server message to the client
        sys.stdout.buffer.flush()  # (never print() here: stdout belongs to the protocol)

    # Two one-way pipes running at the same time:
    client_side = asyncio.create_task(pump(stdin_reader, to_server, on_client_message))  # client -> server
    server_side = asyncio.create_task(pump(server.stdout, to_client, on_server_message))  # server -> client
    # Stop when EITHER side closes (the client hung up, or the server exited).
    await asyncio.wait([client_side, server_side], return_when=asyncio.FIRST_COMPLETED)
    if server.returncode is None:
        server.terminate()  # the server is still running: stop it
    for span, _ in pending.values():  # close anything left open
        span.set_status(Status(StatusCode.ERROR, "connection closed"))
        span.end()
    trace.get_tracer_provider().shutdown()  # make sure every span is written before we exit
    return server.returncode or 0


if __name__ == "__main__":
    # Everything after "--" is the command that starts the real server.
    if "--" not in sys.argv:
        sys.exit("usage: python mcp_proxy.py -- <command that starts the real MCP server>")
    sys.exit(asyncio.run(main(sys.argv[sys.argv.index("--") + 1:])))
