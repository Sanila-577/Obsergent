"""agenttrace.init() - one call to trace an agent into AgentTrace.

The SDK is the "inside the agent" recorder:
  init()              sends this program's spans to the AgentTrace server and
                      auto-traces LangChain/LangGraph (every node, model call, tool step)
  proxy_server()      builds a langchain-mcp-adapters connection that starts an MCP
                      server THROUGH the recording proxy, handing it the trace id
  trace_tool_calls()  adds the trace id to every MCP tools/call (MCP SDK v1 doesn't)

Usage (see examples/bookshop/agent.py):
    from agenttrace.sdk import setup as at
    provider = at.init("my-agent")
"""
import os
import sys

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from agenttrace import config


def init(service_name: str, instrument_langchain: bool = True) -> TracerProvider:
    """Send this program's spans to AgentTrace; auto-trace LangChain/LangGraph if installed.

    Call provider.shutdown() before the program exits: spans are sent in batches,
    and the last batch would be lost otherwise.
    """
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    # Batch = collect spans and send them together every few seconds (fast), to /v1/traces.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{config.ENDPOINT}/v1/traces")))
    trace.set_tracer_provider(provider)  # make it the global provider
    if instrument_langchain:
        try:
            # Hooks LangChain's callbacks: one span per graph node, model call and tool step.
            from openinference.instrumentation.langchain import LangChainInstrumentor
            LangChainInstrumentor().instrument(tracer_provider=provider)
        except ImportError:
            pass  # extra "langchain" not installed: only manual spans, no auto-tracing
    return provider


def trace_tool_calls(session):
    """MCP SDK v1 clients don't send trace context; add it to every tools/call (_meta.traceparent).

    The proxy reads it and makes its span a child of the exact tool step that made the call.
    """
    original = session.call_tool  # keep the real method

    async def call_tool(name, arguments=None, *args, **kwargs):
        span = None
        try:  # inside LangGraph, the active tool span is tracked by the instrumentor
            from openinference.instrumentation.langchain import get_current_span
            span = get_current_span()
        except ImportError:
            pass
        meta = dict(kwargs.pop("meta", None) or {})  # keep any meta the caller already set
        # With a span: write ITS context. Without: the ordinary current OpenTelemetry context.
        inject(meta, context=trace.set_span_in_context(span) if span else None)
        return await original(name, arguments, *args, meta=meta, **kwargs)

    session.call_tool = call_tool  # replace the method on this one session object
    return session


def proxy_server(name: str, command: list[str], **connection) -> dict:
    """A langchain-mcp-adapters stdio connection that runs the server through the AgentTrace proxy.

    Call it INSIDE the agent's root span so the proxy learns which trace it belongs to.
    """
    carrier: dict = {}
    inject(carrier)  # {"traceparent": "00-<trace id>-<span id>-01"} of the current span
    env = dict(os.environ)  # the child needs PATH etc.
    if "traceparent" in carrier:
        # Parent for messages that carry no _meta (initialize, tools/list).
        # A dedicated name: the generic TRACEPARENT is often set by other tools.
        env["MCP_PROXY_TRACEPARENT"] = carrier["traceparent"]
    return {"transport": "stdio", "command": sys.executable,
            "args": ["-m", "agenttrace", "proxy", "--name", name, "--", *command],
            "env": env, **connection}
