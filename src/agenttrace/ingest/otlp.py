"""Turn an OTLP export request (protobuf or JSON) into AgentTrace Span objects.

OTLP is the standard wire format of OpenTelemetry. The SDK, the proxies, Jaeger's
exporters... all speak it, which is why AgentTrace needs just ONE receiver.

An OTLP request is nested:   resource_spans -> scope_spans -> spans
  * the resource says WHO sent the spans (service.name, ...)
  * the spans carry the actual steps
We flatten that into a plain list of `Span`.
"""
import base64
import json

from google.protobuf import json_format
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue

from agenttrace.models import Span

KINDS = {0: "UNSPECIFIED", 1: "INTERNAL", 2: "SERVER", 3: "CLIENT", 4: "PRODUCER", 5: "CONSUMER"}
STATUS = {0: "UNSET", 1: "OK", 2: "ERROR"}

# Resource attributes copied onto every span, so they can be queried like span attributes.
# (The proxy writes them once per process: server name and session id.)
KEEP_RESOURCE_ATTRS = ("mcp.server.name", "agenttrace.session.id", "agenttrace.session.command")

# In OTLP/JSON these fields hold hex strings; protobuf-JSON expects base64 for bytes.
ID_FIELDS = {"traceId", "spanId", "parentSpanId"}


def any_value(value: AnyValue):
    """OTLP attribute values are a tagged union; turn them into plain Python values."""
    kind = value.WhichOneof("value")  # which field of the union is set
    if kind == "array_value":
        return [any_value(item) for item in value.array_value.values]
    if kind == "kvlist_value":
        return attributes_to_dict(value.kvlist_value.values)
    if kind == "bytes_value":
        return value.bytes_value.hex()
    return getattr(value, kind) if kind else None  # string_value, int_value, bool_value, double_value


def attributes_to_dict(key_values) -> dict:
    """A list of OTLP key/value pairs -> a plain dict."""
    return {kv.key: any_value(kv.value) for kv in key_values}


def parse_export_request(body: bytes) -> list[Span]:
    """Parse an OTLP/protobuf body (Content-Type: application/x-protobuf)."""
    request = ExportTraceServiceRequest()
    request.ParseFromString(body)
    return spans_from_request(request)


def parse_export_json(body: bytes) -> list[Span]:
    """Parse an OTLP/JSON body (Content-Type: application/json).

    The OTLP/JSON spec writes trace/span ids as HEX strings, while the generic
    protobuf-JSON parser expects BASE64 for bytes fields. So: convert, then parse.
    """
    data = json.loads(body)
    hex_ids_to_base64(data)
    request = ExportTraceServiceRequest()
    json_format.ParseDict(data, request, ignore_unknown_fields=True)
    return spans_from_request(request)


def hex_ids_to_base64(node) -> None:
    """Walk the JSON and rewrite every id field in place (hex -> base64)."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ID_FIELDS and isinstance(value, str):
                node[key] = base64.b64encode(bytes.fromhex(value)).decode() if value else ""
            else:
                hex_ids_to_base64(value)
    elif isinstance(node, list):
        for item in node:
            hex_ids_to_base64(item)


def spans_from_request(request: ExportTraceServiceRequest) -> list[Span]:
    spans: list[Span] = []
    for resource_spans in request.resource_spans:
        resource = attributes_to_dict(resource_spans.resource.attributes)
        service = str(resource.get("service.name", "unknown"))
        inherited = {key: resource[key] for key in KEEP_RESOURCE_ATTRS if key in resource}
        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                spans.append(Span(
                    trace_id=span.trace_id.hex(),  # bytes -> 32 hex chars
                    span_id=span.span_id.hex(),  # bytes -> 16 hex chars
                    parent_span_id=span.parent_span_id.hex() or None,  # empty bytes = a root span
                    name=span.name,
                    kind=KINDS.get(span.kind, "UNSPECIFIED"),
                    service=service,
                    start_ns=span.start_time_unix_nano,
                    end_ns=span.end_time_unix_nano,
                    status_code=STATUS.get(span.status.code, "UNSET"),
                    status_message=span.status.message,
                    # the span's own attributes win over inherited resource attributes
                    attributes=inherited | attributes_to_dict(span.attributes),
                    events=[{"name": event.name, "time_ns": event.time_unix_nano,
                             "attributes": attributes_to_dict(event.attributes)}
                            for event in span.events],
                ))
    return spans
