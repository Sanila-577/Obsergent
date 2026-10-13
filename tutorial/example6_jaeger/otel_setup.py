"""otel_setup.py - send spans to Jaeger (or any OTLP backend) instead of SQLite.

Same function name as tracker.setup_tracing, so the agent and proxy code
barely change. Only the exporter is different - that's OpenTelemetry's promise.

    tracker.py (examples 1-5)   spans -> SQLiteSpanExporter -> traces.db
    otel_setup.py (this one)    spans -> OTLPSpanExporter   -> HTTP -> Jaeger
"""
import os  # to read the endpoint from an environment variable

from opentelemetry import trace  # to register the provider globally
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # ready-made exporter: sends spans over HTTP
from opentelemetry.sdk.resources import Resource  # describes WHO produces the spans
from opentelemetry.sdk.trace import TracerProvider  # factory/manager of tracing
from opentelemetry.sdk.trace.export import BatchSpanProcessor  # collects spans and sends them in batches

# Where the OTLP receiver listens. 4318 is Jaeger's OTLP/HTTP port (docker-compose.yml).
# Override it to send to another backend: export OTEL_EXPORTER_OTLP_ENDPOINT=http://host:4318
OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")


def setup_tracing(service_name: str) -> TracerProvider:
    # service.name is what Jaeger shows in its "Service" drop-down
    # (here: bookshop-agent and mcp-proxy, because each program calls this with its own name).
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    # The standard OTLP/HTTP path for traces is /v1/traces.
    exporter = OTLPSpanExporter(endpoint=f"{OTLP_ENDPOINT}/v1/traces")
    # Batch = spans wait in memory and are sent together every few seconds. Faster
    # than sending one by one (example 1's SimpleSpanProcessor), BUT the last batch
    # is lost if the program exits first, so every program must call
    # provider.shutdown() before it ends (the agent does this in agent.py; the
    # proxy already does at the end of main()).
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)  # make it the global provider
    return provider
