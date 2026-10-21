"""obsergent.init() - one call to trace an agent into Obsergent.

The SDK is the "inside the agent" recorder:
  init()              sends this program's spans to the Obsergent server and
                      auto-traces LangChain/LangGraph (every node, model call, tool step);
                      instrument=["openai", "anthropic"] adds those SDKs' model calls too
  context()           tag everything inside a `with` block with a session id, user id, tags
  proxy_server()      builds a langchain-mcp-adapters connection that starts an MCP
                      server THROUGH the recording proxy, handing it the trace id
  trace_tool_calls()  adds the trace id to every MCP tools/call (MCP SDK v1 doesn't)

Usage (see examples/bookshop/agent.py):
    from obsergent.sdk import setup as at
    provider = at.init("my-agent")
"""
# contextlib.nullcontext: a "do nothing" with-block for when tracing extras are missing.
import contextlib

# importlib loads an instrumentor module by its name at run time.
import importlib

# os: copy the environment variables for the proxy child process.
import os

# sys.executable is the path of the running Python.
import sys

# OpenTelemetry API: the global tracer provider and span helpers.
from opentelemetry import trace

# Sends spans to Obsergent over OTLP/HTTP.
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# Writes the current trace context (traceparent) into a dict.
from opentelemetry.propagate import inject

# Resource: the program name attached to all spans.
from opentelemetry.sdk.resources import Resource

# The object that creates tracers and owns exporters.
from opentelemetry.sdk.trace import TracerProvider

# Batches spans before sending.
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Where the server is (config.endpoint()).
from obsergent import config

# Optional: needs the langchain extra; without it only manual spans are recorded.
try:  # optional extra "langchain": without it only manual spans are recorded
    from openinference.instrumentation.langchain import get_current_span
# The extra is not installed.
except ImportError:
    # Missing package: remember that.
    get_current_span = None

# Optional: lets us tag spans with session/user ids.
try:  # installed together with any of the instrumentor extras
    from openinference.instrumentation import using_attributes
except ImportError:
    # Missing package: remember that.
    using_attributes = None

# Which framework -> (module, class) of its OpenInference instrumentor. Each one is an optional extra:
#   uv pip install "obsergent[langchain]"   "obsergent[openai]"   "obsergent[anthropic]"
INSTRUMENTORS = {
    "langchain": ("openinference.instrumentation.langchain", "LangChainInstrumentor"),
    "openai": ("openinference.instrumentation.openai", "OpenAIInstrumentor"),
    "anthropic": ("openinference.instrumentation.anthropic", "AnthropicInstrumentor"),
}


# Switch on tracing for one framework.
# How often recorded spans are sent to the server (milliseconds): short, so the UI is close to real time.
EXPORT_EVERY_MS = 1000

def instrument_framework(name: str, provider: TracerProvider, required: bool) -> bool:
    """Hook one framework into the provider. A missing optional package is an error only if it was requested."""
    # Unknown name typed by the user.
    if name not in INSTRUMENTORS:
        raise ValueError(f"unknown framework '{name}'; choose from {sorted(INSTRUMENTORS)}")
    # Which module/class to load.
    module_name, class_name = INSTRUMENTORS[name]
    # Try to import the instrumentor.
    try:
        # Load the module, then get the class from it.
        instrumentor = getattr(importlib.import_module(module_name), class_name)
    except ImportError:
        # The user asked for it explicitly: that is an error with a fix hint.
        if required:
            raise RuntimeError(f"'{name}' tracing needs its extra: uv pip install \"obsergent[{name}]\"") from None
        # Not required: silently skip.
        return False  # the default LangChain hook is silently skipped when the extra is not installed
    # Install the hook: from now on every model call / graph step produces a span.
    instrumentor().instrument(tracer_provider=provider)  # one span per model call / graph step
    # Report success.
    return True


# The SDK's main function: call once at the start of your agent.
def init(service_name: str, instrument_langchain: bool = True, instrument: list[str] | None = None) -> TracerProvider:
    """Send this program's spans to Obsergent and auto-trace the frameworks you use.

    LangChain/LangGraph is traced by default when its extra is installed; `instrument=["openai"]`
    (or "anthropic") adds model calls made directly through those SDKs.
    Call provider.shutdown() before the program exits: spans are sent in batches,
    and the last batch would be lost otherwise.
    """
    # Create a provider that labels spans with this program's name.
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    # Batch = collect spans and send them together, to /v1/traces. Every second (the library's default is 5 s), so a question
    # shows up in the UI about a second after it ends.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{config.endpoint()}/v1/traces"),
                                                   schedule_delay_millis=EXPORT_EVERY_MS))
    # Make it the global one so any code can find it.
    trace.set_tracer_provider(provider)  # make it the global provider
    # Frameworks the caller asked for.
    requested = list(instrument or [])
    # Enable each requested framework (error if its extra is missing).
    for name in requested:
        instrument_framework(name, provider, required=True)
    # Also enable LangChain by default, when it is installed.
    if instrument_langchain and "langchain" not in requested:
        instrument_framework("langchain", provider, required=False)  # hooks LangChain's callbacks
    # The caller must call provider.shutdown() at the end to flush the last batch.
    return provider


# Tag spans created inside a `with` block with session / user / tags.
def context(session_id: str = "", user_id: str = "", tags: list[str] | None = None, metadata: dict | None = None):
    """Tag every model/tool span created inside the `with` block, e.g. to group a user's runs:

        with at.context(session_id="chat-42", user_id="alice"):
            await agent.ainvoke(...)

    The values are stored as `session.id`, `user.id`, `tag.tags` and `metadata` on the spans.
    Without the optional instrumentation package this does nothing (no error).
    """
    # Extra not installed: do nothing, no error.
    if using_attributes is None:
        # An empty with-block.
        return contextlib.nullcontext()
    # The real tagging context manager.
    return using_attributes(session_id=session_id, user_id=user_id, tags=tags, metadata=metadata)


# Patch an MCP session so each tools/call carries the trace context.
def trace_tool_calls(session):
    """MCP SDK v1 clients don't send trace context; add it to every tools/call (_meta.traceparent).

    The proxy reads it and makes its span a child of the exact tool step that made the call.
    """
    # Keep the real method.
    original = session.call_tool  # keep the real method

    # The replacement method: same behaviour plus trace context.
    async def call_tool(name, arguments=None, *args, **kwargs):
        # Inside LangGraph the active tool span is tracked by the instrumentor, not by OpenTelemetry.
        span = get_current_span() if get_current_span else None
        # Existing `meta` argument, copied (or empty).
        meta = dict(kwargs.pop("meta", None) or {})  # keep any meta the caller already set
        # With a span: write ITS context. Without: the ordinary current OpenTelemetry context.
        inject(meta, context=trace.set_span_in_context(span) if span else None)
        # Call the real tools/call with the extended meta.
        return await original(name, arguments, *args, meta=meta, **kwargs)

    # Swap the method on this one session object.
    session.call_tool = call_tool  # replace the method on this one session object
    # Return the same session, patched.
    return session


# Build the connection settings that start an MCP server THROUGH the recording proxy.
def proxy_server(name: str, command: list[str], **connection) -> dict:
    """A langchain-mcp-adapters stdio connection that runs the server through the Obsergent proxy.

    Call it INSIDE the agent's root span so the proxy learns which trace it belongs to.
    """
    # An empty dict to receive the trace context.
    carrier: dict = {}
    # Fill it with the current span's traceparent.
    inject(carrier)  # {"traceparent": "00-<trace id>-<span id>-01"} of the current span
    # Copy environment variables (the child needs PATH etc.).
    env = dict(os.environ)  # the child needs PATH etc.
    # Pass the trace id to the proxy via an environment variable.
    if "traceparent" in carrier:
        # Parent for messages that carry no _meta (initialize, tools/list).
        # A dedicated name: the generic TRACEPARENT is often set by other tools.
        env["MCP_PROXY_TRACEPARENT"] = carrier["traceparent"]
    # The settings dict langchain-mcp-adapters understands: run `python -m obsergent.cli proxy ...`.
    return {"transport": "stdio", "command": sys.executable,
            # The proxy is started through the cli module: `python -m obsergent.cli proxy ...`
            "args": ["-m", "obsergent.cli", "proxy", "--name", name, "--", *command],
            "env": env, **connection}
