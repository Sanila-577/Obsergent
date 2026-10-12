"""mcp_tracing.py - OpenTelemetry spans for the MCP client AND the MCP server.

MCP Python SDK v2 does this by itself. langchain-mcp-adapters still needs SDK v1
(mcp<2), which has no tracing, so this file adds the same behaviour by hand:

  client side  trace_client_session(session)
      wraps session.call_tool / list_tools -> one CLIENT span per request, and
      puts the W3C `traceparent` into the message's params._meta.
  server side  instrument_server(mcp)
      wraps the server's request handlers -> one SERVER span per request, using
      the traceparent from params._meta as its parent.

Result: client span and server span share one trace ID, even though they run in
two different processes.
"""
import json  # to turn argument dicts into text for span attributes

from opentelemetry import trace  # to get a tracer
from opentelemetry.propagate import extract, inject  # inject: context -> dict; extract: dict -> context
from opentelemetry.trace import SpanKind, Status, StatusCode  # span role + success/error marker

from mcp import types  # MCP message classes (CallToolRequest, ListToolsRequest, ...)

tracer = trace.get_tracer("mcp-tracing")  # uses whichever provider setup_tracing() installed

# Longest text we store for arguments/results, so huge payloads don't fill the DB.
MAX_CHARS = 2000


def _short(value) -> str:
    """Turn a value into text and cut it at MAX_CHARS."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "...[truncated]"


def _result_text(result) -> str:
    """Join the text blocks of an MCP result into one string."""
    # result.content is a list of blocks (text, image...); only text blocks have .text.
    return "".join(getattr(block, "text", "") for block in getattr(result, "content", []) or [])


# ---------------------------------------------------------------- client side
def trace_client_session(session):
    """Wrap an MCP ClientSession so every request becomes a CLIENT span."""
    # Keep the real methods; our versions below call them after adding tracing.
    original_call_tool = session.call_tool
    original_list_tools = session.list_tools

    async def call_tool(name, arguments=None, *args, **kwargs):
        # Span names follow the OpenTelemetry MCP convention: "<method> <target>".
        # CLIENT kind = "this span is a request we send to another process".
        with tracer.start_as_current_span(f"tools/call {name}", kind=SpanKind.CLIENT) as span:
            span.set_attribute("mcp.method.name", "tools/call")  # OTel standard attribute names
            span.set_attribute("gen_ai.tool.name", name)
            span.set_attribute("mcp.tool.arguments", _short(arguments or {}))  # what we sent
            # Put the current trace context into params._meta so the server can join this trace.
            meta = dict(kwargs.pop("meta", None) or {})  # keep any meta the caller already set
            inject(meta)  # adds meta["traceparent"] (and tracestate if any)
            result = await original_call_tool(name, arguments, *args, meta=meta, **kwargs)
            span.set_attribute("mcp.tool.result", _short(_result_text(result)))  # what came back
            if result.isError:  # the tool itself reported failure
                span.set_status(Status(StatusCode.ERROR, "tool returned isError"))
            return result

    async def list_tools(cursor=None, *, params=None):
        with tracer.start_as_current_span("tools/list", kind=SpanKind.CLIENT) as span:
            span.set_attribute("mcp.method.name", "tools/list")
            # list_tools carries its trace context in params.meta (same _meta field on the wire).
            meta = dict((params.meta if params and params.meta else {}))
            inject(meta)
            # Rebuild the params object, now including the trace context.
            params = types.PaginatedRequestParams(cursor=cursor, _meta=meta)
            result = await original_list_tools(params=params)
            span.set_attribute("mcp.tools.count", len(result.tools))  # how many tools the server offers
            return result

    # Replace the methods on this one session object (monkey-patching).
    # Anyone calling session.call_tool(...) now goes through our traced versions.
    session.call_tool = call_tool
    session.list_tools = list_tools
    return session


# ---------------------------------------------------------------- server side
def instrument_server(mcp):
    """Wrap a FastMCP server's tools/call and tools/list handlers with SERVER spans."""
    # The low-level server keeps a dict: request type -> function that handles it.
    handlers = mcp._mcp_server.request_handlers  # {request type: async handler}

    def wrap(request_type, method):
        original = handlers[request_type]  # the handler FastMCP registered

        async def handler(req):
            # The client's traceparent (if any) lives in params._meta; make it our parent.
            meta = getattr(req.params, "meta", None) if req.params else None
            carrier = meta.model_dump() if meta else {}  # _meta as a plain dict
            parent = extract(carrier)  # dict with "traceparent" -> OpenTelemetry context
            name = f"{method} {req.params.name}" if method == "tools/call" else method
            # context=parent makes this span a child of the client's span.
            # SERVER kind = "this span handles a request from another process".
            with tracer.start_as_current_span(name, context=parent, kind=SpanKind.SERVER) as span:
                span.set_attribute("mcp.method.name", method)
                if method == "tools/call":
                    span.set_attribute("gen_ai.tool.name", req.params.name)
                    span.set_attribute("mcp.tool.arguments", _short(req.params.arguments or {}))
                response = await original(req)  # run the real tool
                if method == "tools/call":
                    result = response.root  # unwrap ServerResult -> CallToolResult
                    span.set_attribute("mcp.tool.result", _short(_result_text(result)))
                    if result.isError:
                        span.set_status(Status(StatusCode.ERROR, "tool returned isError"))
                return response  # hand the unchanged answer back to the SDK

        handlers[request_type] = handler  # swap in our wrapper

    wrap(types.CallToolRequest, "tools/call")
    wrap(types.ListToolsRequest, "tools/list")
