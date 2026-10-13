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


def any_value(v: AnyValue):
    """OTLP attribute values are a tagged union; turn them into plain Python values."""
    kind = v.WhichOneof("value")  # which field of the union is set
    if kind == "array_value":
        return [any_value(x) for x in v.array_value.values]
    if kind == "kvlist_value":
        return {kv.key: any_value(kv.value) for kv in v.kvlist_value.values}
    if kind == "bytes_value":
        return v.bytes_value.hex()
    return getattr(v, kind) if kind else None  # string_value, int_value, bool_value, double_value


def parse_export_request(body: bytes) -> list[Span]:
    """Parse an OTLP/protobuf body (Content-Type: application/x-protobuf)."""
    req = ExportTraceServiceRequest()
    req.ParseFromString(body)
    return _spans_from_request(req)


def parse_export_json(body: bytes) -> list[Span]:
    """Parse an OTLP/JSON body (Content-Type: application/json).

    The OTLP/JSON spec writes trace/span ids as HEX strings, while the generic
    protobuf-JSON parser expects BASE64 for bytes fields. So: convert, then parse.
    """
    data = json.loads(body)
    _hex_ids_to_base64(data)
    req = ExportTraceServiceRequest()
    json_format.ParseDict(data, req, ignore_unknown_fields=True)
    return _spans_from_request(req)


def _hex_ids_to_base64(node) -> None:
    """Walk the JSON and rewrite every id field in place (hex -> base64)."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ID_FIELDS and isinstance(value, str):
                node[key] = base64.b64encode(bytes.fromhex(value)).decode() if value else ""
            else:
                _hex_ids_to_base64(value)
    elif isinstance(node, list):
        for item in node:
            _hex_ids_to_base64(item)


def _spans_from_request(req: ExportTraceServiceRequest) -> list[Span]:
    spans: list[Span] = []
    for rs in req.resource_spans:
        resource = {kv.key: any_value(kv.value) for kv in rs.resource.attributes}
        service = str(resource.get("service.name", "unknown"))
        inherited = {k: resource[k] for k in KEEP_RESOURCE_ATTRS if k in resource}
        for ss in rs.scope_spans:
            for s in ss.spans:
                spans.append(Span(
                    trace_id=s.trace_id.hex(),  # bytes -> 32 hex chars
                    span_id=s.span_id.hex(),  # bytes -> 16 hex chars
                    parent_span_id=s.parent_span_id.hex() or None,  # empty bytes = a root span
                    name=s.name,
                    kind=KINDS.get(s.kind, "UNSPECIFIED"),
                    service=service,
                    start_ns=s.start_time_unix_nano,
                    end_ns=s.end_time_unix_nano,
                    status_code=STATUS.get(s.status.code, "UNSET"),
                    status_message=s.status.message,
                    # span's own attributes win over inherited resource attributes
                    attributes=inherited | {kv.key: any_value(kv.value) for kv in s.attributes},
                    events=[{"name": e.name, "time_ns": e.time_unix_nano,
                             "attributes": {kv.key: any_value(kv.value) for kv in e.attributes}}
                            for e in s.events],
                ))
    return spans
