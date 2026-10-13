"""A proxy SESSION = one proxy process = one MCP server connection.

Why sessions exist: closed apps (Claude Desktop, Cursor) send no trace id, so
every request they make would become its own unrelated trace. Every span of one
proxy process carries the same `agenttrace.session.id`, so the API can group
them again ("show me everything Claude Desktop did with the filesystem server").

The session facts travel as OpenTelemetry RESOURCE attributes (once per process,
not repeated in every span); ingest copies them onto each span.
"""
import uuid
from dataclasses import dataclass, field

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from agenttrace import config
from agenttrace.proxy.redact import safe_command


@dataclass
class Session:
    server_name: str  # the name given with --name, shown in traces
    command: list[str] = field(default_factory=list)  # how the real server was started
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)  # new for every proxy process

    def resource_attributes(self) -> dict:
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
    provider = TracerProvider(resource=Resource.create(session.resource_attributes()))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{config.ENDPOINT}/v1/traces")))
    return provider
