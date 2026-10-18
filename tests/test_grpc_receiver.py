"""OTLP over gRPC: spans sent with a real gRPC client end up in storage, like the HTTP endpoint."""
import grpc
import pytest
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2_grpc

from agenttrace.server.grpc_receiver import start_grpc_server
from agenttrace.storage.sqlite import SQLiteStorage
from test_ingest_and_api import make_spans


@pytest.fixture
def receiver(tmp_path):
    storage = SQLiteStorage(tmp_path / "grpc.db")
    server, port = start_grpc_server(storage, "127.0.0.1", 0)  # port 0: any free port
    yield storage, port
    server.stop(grace=None)


def test_spans_sent_over_grpc_are_stored(receiver):
    storage, port = receiver
    with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
        stub = trace_service_pb2_grpc.TraceServiceStub(channel)
        stub.Export(encode_spans(make_spans()))  # the call returns once the batch is stored
    (trace,) = storage.list_traces()
    assert trace["span_count"] == 4 and trace["root_name"] == "agent.run" and trace["tool_calls"] == 3


def test_a_busy_port_is_reported_clearly(receiver):
    storage, port = receiver
    with pytest.raises(RuntimeError, match="could not listen"):
        start_grpc_server(storage, "127.0.0.1", port)
