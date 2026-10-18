"""OTLP over gRPC: the second way OpenTelemetry exporters can deliver spans.

The HTTP receiver (`POST /v1/traces`, server/app.py) covers the Python SDK and the proxies. Some
senders only speak gRPC. WSO2 API Manager is one: its built-in OpenTelemetry exporter
(`[apim.open_telemetry] remote_tracer.name = "otlp"`) uses gRPC, so without this receiver the
gateway's own spans could not reach AgentTrace.

    gateway ──gRPC TraceService/Export (port 4317)──► TraceReceiver ──► same ingest as HTTP ──► SQLite

Optional: it needs the `grpcio` package (`uv pip install "agenttrace[grpc]"`). Start it with
`agenttrace up --grpc`.
"""
# futures.ThreadPoolExecutor: the worker threads that handle incoming gRPC calls.
from concurrent import futures

# The empty "accepted" reply message.
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse

# Same conversion as the HTTP route uses.
from agenttrace.ingest.otlp import spans_from_request

# Same saving logic as the HTTP route uses.
from agenttrace.ingest.pipeline import ingest_spans

# The database interface.
from agenttrace.storage.base import Backend

# grpcio is optional; the rest of AgentTrace works without it.
try:  # optional extra: the rest of AgentTrace works without it
    # The gRPC library.
    import grpc
    from opentelemetry.proto.collector.trace.v1 import trace_service_pb2_grpc
except ImportError:
    # Missing: remember that, so start_grpc_server can give a clear error.
    grpc = trace_service_pb2_grpc = None

# The parent class the generated gRPC code gives us (a stand-in `object` if grpc is missing).
BaseServicer = trace_service_pb2_grpc.TraceServiceServicer if trace_service_pb2_grpc else object


# The object that answers the Export call.
class TraceReceiver(BaseServicer):
    """Implements the OTLP `TraceService`: one RPC, `Export`, that carries a batch of spans."""

    # Keep the database to write into.
    def __init__(self, backend: Backend):
        # Remember it.
        self.backend = backend

    # Called by gRPC for every batch of spans the sender exports (name fixed by the OTLP definition).
    def Export(self, request, context):  # noqa: N802 - the method name is fixed by the OTLP gRPC service definition
        """Turn the batch into Span objects and store it, exactly like the HTTP endpoint does."""
        # Same path as HTTP: convert, normalize, save.
        ingest_spans(spans_from_request(request), self.backend)
        # Empty message = "accepted".
        return ExportTraceServiceResponse()  # an empty message means "accepted"


# Start listening in background threads and return immediately.
def start_grpc_server(backend: Backend, host: str, port: int):
    """Start the receiver in background threads. Returns (server, the port actually bound)."""
    # grpcio not installed: explain how to fix.
    if grpc is None:
        raise RuntimeError('the gRPC receiver needs grpcio: uv pip install "agenttrace[grpc]"')
    # so_reuseport=0: by default gRPC lets two servers share a port, which would silently split the spans
    # between AgentTrace and another collector. We want a clear error instead.
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4), options=[("grpc.so_reuseport", 0)])
    # Register our receiver as the OTLP TraceService.
    trace_service_pb2_grpc.add_TraceServiceServicer_to_server(TraceReceiver(backend), server)
    # Bind the port (0 = let the OS choose a free one; tests use that).
    try:
        # Listen without TLS on host:port.
        bound_port = server.add_insecure_port(f"{host}:{port}")  # port 0 = pick a free one (used by tests)
    # Newer grpcio raises on failure; older returns 0.
    except RuntimeError:  # newer grpcio raises; older versions return 0
        # Normalise to 0 = failure.
        bound_port = 0
    # Port unavailable: tell the user.
    if bound_port == 0:
        raise RuntimeError(f"could not listen on {host}:{port} (is another OpenTelemetry collector running?)")
    # Begin serving.
    server.start()
    # The caller keeps the server to stop it later.
    return server, bound_port
