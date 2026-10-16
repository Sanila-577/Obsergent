"""Send real OpenTelemetry spans through the OTLP endpoint and read them back."""
from fastapi.testclient import TestClient
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agenttrace.server.app import create_app
from agenttrace.storage.sqlite import SQLiteStorage
from conftest import post_spans


def make_spans():
    """A tiny fake agent run: agent.run with the same tool call three times."""
    mem = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "test-agent"}))
    provider.add_span_processor(SimpleSpanProcessor(mem))
    tracer = provider.get_tracer("t")
    with tracer.start_as_current_span("agent.run"):
        for attempt in range(3):  # the same call three times -> a loop smell
            with tracer.start_as_current_span("tools/call search") as s:
                s.set_attribute("attempt", attempt)
                s.set_attribute("mcp.method.name", "tools/call")
                s.set_attribute("gen_ai.tool.name", "search")
                s.set_attribute("mcp.tool.arguments", '{"q": "python"}')
    return mem.get_finished_spans()


def test_roundtrip(tmp_path):
    client = TestClient(create_app(SQLiteStorage(tmp_path / "t.db")))
    assert post_spans(client, make_spans()).status_code == 200
    traces = client.get("/api/traces").json()
    assert len(traces) == 1 and traces[0]["span_count"] == 4 and traces[0]["tool_calls"] == 3
    assert traces[0]["root_name"] == "agent.run"
    detail = client.get(f"/api/traces/{traces[0]['trace_id']}").json()
    assert {s["name"] for s in detail["spans"]} == {"agent.run", "tools/call search"}
    assert detail["smells"][0]["type"] == "loop"


def test_trace_id_prefix_works(tmp_path):
    client = TestClient(create_app(SQLiteStorage(tmp_path / "t.db")))
    post_spans(client, make_spans())
    full = client.get("/api/traces").json()[0]["trace_id"]
    assert client.get(f"/api/traces/{full[:8]}").json()["trace_id"] == full
    assert client.get("/api/traces/ffffffff").status_code == 404


def test_rejects_other_content_types(tmp_path):
    client = TestClient(create_app(SQLiteStorage(tmp_path / "t.db")))
    assert client.post("/v1/traces", content=b"x", headers={"content-type": "text/plain"}).status_code == 415


def test_rejects_garbage_protobuf(tmp_path):
    client = TestClient(create_app(SQLiteStorage(tmp_path / "t.db")))
    r = client.post("/v1/traces", content=b"\xff\xff not protobuf",
                    headers={"content-type": "application/x-protobuf"})
    assert r.status_code == 400
