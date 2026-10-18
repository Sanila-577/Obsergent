"""Turn an OTLP export request (protobuf or JSON) into AgentTrace Span objects.

OTLP is the standard wire format of OpenTelemetry. The SDK, the proxies, Jaeger's
exporters... all speak it, which is why AgentTrace needs just ONE receiver.

An OTLP request is nested:   resource_spans -> scope_spans -> spans
  * the resource says WHO sent the spans (service.name, ...)
  * the spans carry the actual steps
We flatten that into a plain list of `Span`.
"""
# base64 converts between hex-id bytes and the text form protobuf-JSON wants.
import base64

# json parses OTLP/JSON bodies.
import json

# json_format converts JSON dicts into protobuf objects.
from google.protobuf import json_format

# ExportTraceServiceRequest is the protobuf class of one OTLP export; AnyValue is one attribute value.
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue

# Span is AgentTrace's own shape.
from agenttrace.models import Span

# OTLP stores the span kind and status as numbers; these tables turn them into words.
KINDS = {0: "UNSPECIFIED", 1: "INTERNAL", 2: "SERVER", 3: "CLIENT", 4: "PRODUCER", 5: "CONSUMER"}
STATUS = {0: "UNSET", 1: "OK", 2: "ERROR"}

# Resource attributes copied onto every span, so they can be queried like span attributes.
# (The proxy writes them once per process: server name and session id.)
KEEP_RESOURCE_ATTRS = ("mcp.server.name", "agenttrace.session.id", "agenttrace.session.command")

# In OTLP/JSON these fields hold hex strings; protobuf-JSON expects base64 for bytes.
ID_FIELDS = {"traceId", "spanId", "parentSpanId"}


def any_value(value: AnyValue):
    """OTLP attribute values are a tagged union; turn them into plain Python values."""
    # which field of the union is set
    kind = value.WhichOneof("value")  # which field of the union is set
    # A list value: convert every item recursively.
    if kind == "array_value":
        return [any_value(item) for item in value.array_value.values]
    # A nested map: convert it into a dict.
    if kind == "kvlist_value":
        return attributes_to_dict(value.kvlist_value.values)
    # Raw bytes: show as hex text.
    if kind == "bytes_value":
        return value.bytes_value.hex()
    # Plain values: read the field named by `kind`; None if nothing is set.
    return getattr(value, kind) if kind else None  # string_value, int_value, bool_value, double_value


def attributes_to_dict(key_values) -> dict:
    """A list of OTLP key/value pairs -> a plain dict."""
    # One dict entry per key/value pair.
    return {kv.key: any_value(kv.value) for kv in key_values}


def parse_export_request(body: bytes) -> list[Span]:
    """Parse an OTLP/protobuf body (Content-Type: application/x-protobuf)."""
    # An empty request object, filled from the binary body.
    request = ExportTraceServiceRequest()
    request.ParseFromString(body)
    # Flatten it into Spans.
    return spans_from_request(request)


def parse_export_json(body: bytes) -> list[Span]:
    """Parse an OTLP/JSON body (Content-Type: application/json).

    The OTLP/JSON spec writes trace/span ids as HEX strings, while the generic
    protobuf-JSON parser expects BASE64 for bytes fields. So: convert, then parse.
    """
    # Parse the JSON text into dicts.
    data = json.loads(body)
    # Fix the id fields in place.
    hex_ids_to_base64(data)
    # Fill a protobuf request from the dict; unknown fields are ignored instead of failing.
    request = ExportTraceServiceRequest()
    json_format.ParseDict(data, request, ignore_unknown_fields=True)
    return spans_from_request(request)


def hex_ids_to_base64(node) -> None:
    """Walk the JSON and rewrite every id field in place (hex -> base64)."""
    if isinstance(node, dict):
        for key, value in node.items():
            # An id field: hex text -> bytes -> base64 text (empty stays empty).
            if key in ID_FIELDS and isinstance(value, str):
                node[key] = base64.b64encode(bytes.fromhex(value)).decode() if value else ""
            else:
                # Anything else: look inside it.
                hex_ids_to_base64(value)
    elif isinstance(node, list):
        for item in node:
            hex_ids_to_base64(item)


def spans_from_request(request: ExportTraceServiceRequest) -> list[Span]:
    # The flat result.
    spans: list[Span] = []
    # One resource_spans block per sending program.
    for resource_spans in request.resource_spans:
        # Facts about the sender.
        resource = attributes_to_dict(resource_spans.resource.attributes)
        # Its program name.
        service = str(resource.get("service.name", "unknown"))
        # The resource attributes we copy onto every span.
        inherited = {key: resource[key] for key in KEEP_RESOURCE_ATTRS if key in resource}
        # Each block holds one or more instrumentation scopes, each with spans.
        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                # Build one AgentTrace Span from the protobuf span.
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
    # All spans of the request, flattened.
    return spans
