"""A proxy SESSION = one proxy process = one MCP server connection.

Why sessions exist: closed apps (Claude Desktop, Cursor) send no trace id, so
every request they make would become its own unrelated trace. Every span of one
proxy process carries the same `agenttrace.session.id`, so the API can group
them again ("show me everything Claude Desktop did with the filesystem server").

The session facts travel as OpenTelemetry RESOURCE attributes (once per process,
not repeated in every span); ingest copies them onto each span.
"""
# uuid makes random unique ids.
import uuid

# dataclass/field generate the class boilerplate.
from dataclasses import dataclass, field

# The exporter that sends spans as OTLP over HTTP to the AgentTrace server.
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# Resource = facts about the producing program, attached to every span it makes.
from opentelemetry.sdk.resources import Resource

# TracerProvider creates tracers; BatchSpanProcessor sends spans in batches in the background.
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# config.endpoint() is the AgentTrace server address.
from agenttrace import config

# safe_command hides secrets in the server command.
from agenttrace.proxy.redact import safe_command


@dataclass
class Session:
    server_name: str  # the name given with --name, shown in traces
    command: list[str] = field(default_factory=list)  # how the real server was started
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)  # new for every proxy process

    def resource_attributes(self) -> dict:
        # The facts attached to every span of this process.
        attrs = {
            "service.name": "agenttrace-proxy",  # which program produced the spans
            "mcp.server.name": self.server_name,
            "agenttrace.session.id": self.session_id,
        }
        if self.command:
            attrs["agenttrace.session.command"] = safe_command(self.command)  # never raw: may hold secrets
        return attrs


def make_provider(session: Session) -> TracerProvider:
    """A tracer provider that tags every span with the session and sends them to the server in batches."""
    # The provider stamps every span with the session's resource attributes.
    provider = TracerProvider(resource=Resource.create(session.resource_attributes()))
    # Batches of finished spans are POSTed to <server>/v1/traces in the background.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{config.endpoint()}/v1/traces")))
    return provider
