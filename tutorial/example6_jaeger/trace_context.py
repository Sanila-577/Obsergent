"""trace_context.py - pass the agent's trace ID to the proxy.

MCP SDK v1 (needed by langchain-mcp-adapters today) does not send trace
context by itself, so we add it in two places:
  1. MCP_PROXY_TRACEPARENT env var when the proxy process starts (for setup messages)
  2. params._meta.traceparent on every tool call (so each call joins the trace)
MCP SDK v2 does step 2 automatically.

A traceparent is the "ticket number" of a span, e.g.
    00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
    version - trace id (32 hex) - parent span id (16 hex) - flags (01 = record it)
"""
import os  # to copy and extend the environment for the proxy process

from opentelemetry import trace  # to put a span into a context
from opentelemetry.propagate import inject  # context -> {"traceparent": "..."}


def current_traceparent() -> dict:
    """W3C trace context of the innermost active span, e.g. {"traceparent": "00-...-01"}."""
    span = None
    try:  # LangGraph tool runs are tracked by the instrumentor, not the OTel context
        # So "the current span" according to OpenTelemetry would only be agent.run.
        # The instrumentor can tell us the real current one (e.g. the tool step
        # search_books), which makes the proxy span a child of the exact tool step.
        from openinference.instrumentation.langchain import get_current_span
        span = get_current_span()
    except ImportError:
        pass  # instrumentor not installed: fall back to OpenTelemetry's own current span
    carrier: dict = {}  # an empty dict that inject() fills in
    # With a span: write that span's context. With None: write the ordinary current context.
    inject(carrier, context=trace.set_span_in_context(span) if span else None)
    return carrier


def proxy_env(**extra) -> dict:
    """Environment for the proxy process: keep PATH etc., add the trace context."""
    env = dict(os.environ)  # the child must keep PATH, HOME, ... or it can't start
    # Session-level parent for messages that carry no _meta (initialize, tools/list).
    env.update({"MCP_PROXY_TRACEPARENT": tp} if (tp := current_traceparent().get("traceparent")) else {})
    env.update(extra)  # e.g. TRACKER_DB: where the proxy must write its spans
    return env


def add_trace_context(session):
    """Wrap session.call_tool so every tools/call carries the current traceparent."""
    original = session.call_tool  # keep the real method

    async def call_tool(name, arguments=None, *args, **kwargs):
        meta = dict(kwargs.pop("meta", None) or {})  # keep any meta the caller already set
        meta.update(current_traceparent())  # add traceparent of the current tool step
        # The proxy reads it from params._meta and makes its span a child of that tool step.
        return await original(name, arguments, *args, meta=meta, **kwargs)

    session.call_tool = call_tool  # replace the method on this one session object
    return session
