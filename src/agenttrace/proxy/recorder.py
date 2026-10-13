"""The heart of the proxy: turn MCP messages into spans. Knows NOTHING about transports.

Both proxies (stdio.py, http.py) feed every JSON-RPC message through this class:

    client ──request──► on_request()  ──► (message, slightly extended) ──► real server
    client ◄─response── on_response() ◄── (message, unchanged)         ◄── real server

  * a REQUEST has "method" and "id": open a span (start the clock)
  * the matching RESPONSE has the same "id": record the result, close the span
  * a NOTIFICATION has a method but no id (no answer comes back): just forward it

Trace joining: if the request carries `params._meta.traceparent` (the agent's
tool step), the span becomes its child. Otherwise it uses the session-level parent
from MCP_PROXY_TRACEPARENT, or starts a new trace (closed apps).
"""
import json
import os

from opentelemetry import context, trace
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import SpanKind, Status, StatusCode

from agenttrace.proxy.redact import to_attr

# Set by the AgentTrace SDK (never the generic TRACEPARENT: CI systems and other
# tools set that one for their own traces, and the proxy would silently record nothing).
SESSION_ENV = "MCP_PROXY_TRACEPARENT"
TOOLS_LIMIT = 200_000  # a tools/list result can be big; the drift check needs all of it


class Recorder:
    def __init__(self, tracer: trace.Tracer, server_name: str):
        self.tracer = tracer
        self.server_name = server_name
        # request id -> (open span, method). Filled on the request, emptied on the response.
        self.pending: dict = {}
        tp = os.environ.get(SESSION_ENV)
        # With the variable: a context pointing at the agent's span.
        # Without it: an empty context, so every request starts its own trace.
        self.session_ctx = extract({"traceparent": tp}) if tp else context.Context()

    # ---------------------------------------------------------------- client -> server
    def on_request(self, msg: dict) -> dict:
        """Called for every message the client sends. Starts a span for each request."""
        if "method" not in msg or "id" not in msg:
            return msg  # a notification, or the client's answer to a server request: nothing to time
        method = msg["method"]  # e.g. initialize, tools/list, tools/call
        params = msg.get("params") or {}
        msg["params"] = params
        meta = params.setdefault("_meta", {})  # the protocol's place for extra metadata
        # Parent = the agent's tool step if the request carries a traceparent, else the session parent.
        parent = extract(meta) if "traceparent" in meta else self.session_ctx
        target = params.get("name") or params.get("uri") or ""  # the tool name or resource uri
        # start_span (not "as current"): we end it later, when the response arrives.
        span = self.tracer.start_span(f"{method} {target}".strip(), context=parent, kind=SpanKind.CLIENT)
        span.set_attribute("mcp.method.name", method)  # OpenTelemetry MCP attribute names
        span.set_attribute("mcp.server.name", self.server_name)
        span.set_attribute("jsonrpc.request.id", str(msg["id"]))
        if method == "tools/call":
            span.set_attribute("gen_ai.operation.name", "execute_tool")
            span.set_attribute("gen_ai.tool.name", target)
            span.set_attribute("mcp.tool.arguments", to_attr(params.get("arguments", {})))
        elif "uri" in params:
            span.set_attribute("mcp.resource.uri", str(params["uri"]))
        # Overwrite _meta.traceparent with THIS span's id: a traced server now sees the proxy span as its parent.
        inject(meta, context=trace.set_span_in_context(span))
        self.pending[msg["id"]] = (span, method)
        return msg

    # ---------------------------------------------------------------- server -> client
    def on_response(self, msg: dict) -> dict:
        """Called for every message the server sends. Finishes the span of the matching request."""
        if "result" not in msg and "error" not in msg:
            return msg  # a notification or a request from the server
        entry = self.pending.pop(msg.get("id"), None)
        if entry is None:
            return msg  # a response we never saw the request for
        span, method = entry
        if "error" in msg:  # protocol-level error (unknown method, invalid params...)
            err = msg["error"] if isinstance(msg["error"], dict) else {}
            span.set_status(Status(StatusCode.ERROR, str(err.get("message", "error"))))
            span.set_attribute("mcp.error.code", int(err.get("code", 0)))
        else:
            result = msg["result"]
            if isinstance(result, dict) and result.get("isError"):  # the tool itself reported failure
                span.set_status(Status(StatusCode.ERROR, "tool returned isError"))
            if method == "tools/list" and isinstance(result, dict) and "tools" in result:
                # Keep the full tool list (not redacted: it describes the server, it holds no user data).
                # Ingest turns it into a "tool snapshot" so changes can be detected.
                span.set_attribute("mcp.tools", json.dumps(result["tools"], sort_keys=True)[:TOOLS_LIMIT])
            else:
                span.set_attribute("mcp.result", to_attr(result))
        span.end()  # duration = request seen -> response seen
        return msg

    def close_ids(self, ids, reason: str) -> None:
        """Close the spans of specific requests that will never get an answer (used by the HTTP proxy)."""
        for msg_id in ids:
            entry = self.pending.pop(msg_id, None)
            if entry:
                entry[0].set_status(Status(StatusCode.ERROR, reason))
                entry[0].end()

    def close_pending(self, reason: str = "connection closed") -> None:
        """The connection ended: close every span still waiting for an answer, marked as an error."""
        for span, _ in self.pending.values():
            span.set_status(Status(StatusCode.ERROR, reason))
            span.end()
        self.pending.clear()
