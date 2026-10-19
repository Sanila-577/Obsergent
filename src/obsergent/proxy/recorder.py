"""The heart of the proxy: turn MCP messages into spans. Knows NOTHING about transports.

Both proxies (stdio.py, http.py) feed every JSON-RPC message through this class:

    client ──request──► on_request()  ──► (message, slightly extended) ──► real server
    client ◄─response── on_response() ◄── (message, unchanged)         ◄── real server

  * a REQUEST has "method" and "id": open a span (start the clock)
  * the matching RESPONSE has the same "id": record the result, close the span
  * a NOTIFICATION has a method but no id (no answer comes back): just forward it

JSON-RPC 2.0 in one picture (this is the message format MCP uses):
    request       {"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"search_books","arguments":{...}}}
    response      {"jsonrpc":"2.0","id":7,"result":{...}}   or   {"jsonrpc":"2.0","id":7,"error":{"code":-32601,...}}
    notification  {"jsonrpc":"2.0","method":"notifications/initialized"}      (no id, nobody answers)
The `id` is what lets us pair an answer with its question.

Trace joining: if the request carries `params._meta.traceparent` (the agent's
tool step), the span becomes its child. Otherwise it uses the session-level parent
from MCP_PROXY_TRACEPARENT, or starts a new trace (closed apps).
"""
# json: turn the tool list into text.
import json

# os: read the MCP_PROXY_TRACEPARENT environment variable.
import os

# NamedTuple: a tiny immutable record type.
from typing import NamedTuple

# OpenTelemetry API: `context` (who is the current parent), `trace` (spans and tracers).
from opentelemetry import context, trace

# extract(): read a traceparent from a dict into a context. inject(): write the current context into a dict.
from opentelemetry.propagate import extract, inject

# SpanKind says what role a span plays; Status/StatusCode mark success or failure.
from opentelemetry.trace import SpanKind, Status, StatusCode

# to_attr(): redact secrets, turn into JSON text, truncate.
from obsergent.proxy.redact import to_attr

# Set by the Obsergent SDK (never the generic TRACEPARENT: CI systems and other
# tools set that one for their own traces, and the proxy would silently record nothing).
SESSION_ENV = "MCP_PROXY_TRACEPARENT"
# A tools/list result can be big; the drift check needs all of it, so allow up to 200,000 characters.
TOOLS_LIMIT = 200_000


# A request that is waiting for its answer.
class Pending(NamedTuple):
    """A request that has been sent but not answered yet."""
    span: trace.Span  # the open span of the request
    method: str  # e.g. "tools/list": the response handler needs it


class Recorder:
    def __init__(self, tracer: trace.Tracer, server_name: str):
        # The tracer creates spans (comes from sessions.make_provider).
        self.tracer = tracer
        # The name shown in the UI for the MCP server being recorded.
        self.server_name = server_name
        # request id -> Pending. Filled on the request, emptied on the response.
        self.pending: dict[object, Pending] = {}
        # The agent (SDK) passes its current span to the proxy process through this environment variable.
        tp = os.environ.get(SESSION_ENV)
        # With the variable: a context pointing at the agent's span.
        # Without it: an empty context, so every request starts its own trace.
        self.session_ctx = extract({"traceparent": tp}) if tp else context.Context()

    # ---------------------------------------------------------------- client -> server
    def on_request(self, msg: dict, extra: dict | None = None) -> dict:
        """Called for every message the client sends. Starts a span for each request.

        `extra` = more span attributes known to the transport (for example who the HTTP caller is).
        """
        # Only a request has both "method" and "id".
        if "method" not in msg or "id" not in msg:
            return msg  # a notification, or the client's answer to a server request: nothing to time
        # The method name tells what the client wants: initialize, tools/list, tools/call ...
        method = msg["method"]  # e.g. initialize, tools/list, tools/call
        # params may be missing or null; use an empty dict then.
        params = msg.get("params") or {}
        # Put it back so the message definitely has a params dict we can add _meta to.
        msg["params"] = params
        # `_meta` is the protocol's reserved place for extra metadata; create it if absent.
        meta = params.setdefault("_meta", {})  # the protocol's place for extra metadata
        # Parent = the agent's tool step if the request carries a traceparent, else the session parent.
        parent = extract(meta) if "traceparent" in meta else self.session_ctx
        # For tools/call the name is the tool; for resources/read the uri is the resource.
        target = params.get("name") or params.get("uri") or ""  # the tool name or resource uri
        # start_span (not "as current"): we end it later, when the response arrives.
        span = self.tracer.start_span(f"{method} {target}".strip(), context=parent, kind=SpanKind.CLIENT)
        # Record what the request was, using OpenTelemetry's MCP attribute names.
        span.set_attribute("mcp.method.name", method)  # OpenTelemetry MCP attribute names
        span.set_attribute("mcp.server.name", self.server_name)
        span.set_attribute("jsonrpc.request.id", str(msg["id"]))
        # Add whatever the transport told us (e.g. HTTP caller identity).
        span.set_attributes(extra or {})
        if method == "tools/call":
            # Mark it as "a tool was executed" and store which tool and with which (redacted) arguments.
            span.set_attribute("gen_ai.operation.name", "execute_tool")
            span.set_attribute("gen_ai.tool.name", target)
            span.set_attribute("mcp.tool.arguments", to_attr(params.get("arguments", {})))
        elif "uri" in params:
            # A resource read: store which resource.
            span.set_attribute("mcp.resource.uri", str(params["uri"]))
        # Overwrite _meta.traceparent with THIS span's id: a traced server now sees the proxy span as its parent.
        inject(meta, context=trace.set_span_in_context(span))
        # Remember the open span under the request id; on_response will find it again.
        self.pending[msg["id"]] = Pending(span, method)
        # Return the (slightly extended) message; the proxy forwards it to the real server.
        return msg

    # ---------------------------------------------------------------- server -> client
    def on_response(self, msg: dict, extra: dict | None = None) -> dict:
        """Called for every message the server sends. Finishes the span of the matching request.

        `extra` = more span attributes known to the transport (HTTP status, gateway decision...).
        """
        # Only a response has "result" or "error".
        if "result" not in msg and "error" not in msg:
            return msg  # a notification or a request from the server
        # Take the matching open span out of the pending table (None if we never saw the request).
        entry = self.pending.pop(msg.get("id"), None)
        if entry is None:
            return msg  # a response we never saw the request for
        # Unpack the named tuple.
        span, method = entry.span, entry.method
        # Add the transport's extra facts.
        span.set_attributes(extra or {})
        if "error" in msg:  # protocol-level error (unknown method, invalid params...)
            # The error should be a dict {"code":..., "message":...}; be safe if it is not.
            err = msg["error"] if isinstance(msg["error"], dict) else {}
            # Mark the span as failed with the server's message.
            span.set_status(Status(StatusCode.ERROR, str(err.get("message", "error"))))
            span.set_attribute("mcp.error.code", int(err.get("code", 0)))
        else:
            result = msg["result"]
            # A tool can "succeed" at the protocol level yet report failure with isError: true.
            if isinstance(result, dict) and result.get("isError"):  # the tool itself reported failure
                span.set_status(Status(StatusCode.ERROR, "tool returned isError"))
            if method == "tools/list" and isinstance(result, dict) and "tools" in result:
                # Keep the full tool list (not redacted: it describes the server, it holds no user data).
                # Ingest turns it into a "tool snapshot" so changes can be detected.
                span.set_attribute("mcp.tools", json.dumps(result["tools"], sort_keys=True)[:TOOLS_LIMIT])
            else:
                # Everything else: store the redacted, truncated result.
                span.set_attribute("mcp.result", to_attr(result))
        span.end()  # duration = request seen -> response seen
        return msg

    def close_ids(self, ids, reason: str, extra: dict | None = None) -> None:
        """Close the spans of requests that will never get an answer, marked as errors."""
        for msg_id in ids:
            # Remove from the waiting table (None if it was already answered).
            entry = self.pending.pop(msg_id, None)
            if entry:
                # Record what we know, mark it failed with the reason, and finish it.
                entry.span.set_attributes(extra or {})
                entry.span.set_status(Status(StatusCode.ERROR, reason))
                entry.span.end()

    def close_pending(self, reason: str = "connection closed") -> None:
        """The connection ended: close every span still waiting for an answer."""
        # list(...) copies the ids because close_ids removes entries while we loop.
        self.close_ids(list(self.pending), reason)
