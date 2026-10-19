"""The Streamable HTTP proxy, with a fake upstream MCP server (httpx.MockTransport)."""
import json
from typing import NamedTuple

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from obsergent.proxy.http import create_proxy_app

UPSTREAM = "http://upstream.test/mcp?token=SECRET"


def fake_upstream(request: httpx.Request) -> httpx.Response:
    """What the real remote server would answer."""
    msg = json.loads(request.content)
    if "id" not in msg:  # notification -> 202 and no body
        return httpx.Response(202)
    method = msg["method"]
    if method == "initialize":
        result = {"serverInfo": {"name": "Remote"}}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"], "result": result},
                              headers={"mcp-session-id": "abc"})
    if method == "tools/list":
        tools = [{"name": "search", "description": "Search", "inputSchema": {}}]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": tools}})
    if msg["params"]["name"] == "stream_me":  # answer as an SSE stream
        result = {"content": [{"type": "text", "text": "streamed"}]}
        event = json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result})
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=f"event: message\ndata: {event}\n\n".encode())
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"],
                                     "result": {"content": [{"type": "text", "text": "found"}]}})


class Harness(NamedTuple):
    client: TestClient  # talks to the proxy
    spans: InMemorySpanExporter  # what the proxy recorded
    sessions: list  # the Session objects the proxy created


@pytest.fixture
def harness():
    spans = InMemorySpanExporter()
    sessions = []

    def provider_factory(session):  # capture spans in memory instead of sending them anywhere
        sessions.append(session)
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(spans))
        return provider

    app = create_proxy_app({"demo": UPSTREAM}, provider_factory=provider_factory,
                           transport=httpx.MockTransport(fake_upstream))
    with TestClient(app) as client:  # the with-block runs the app's start-up and shut-down
        yield Harness(client, spans, sessions)


def rpc(msg_id, method, **params):
    return {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}


def test_json_responses_are_recorded_and_forwarded_unchanged(harness):
    reply = harness.client.post("/mcp/demo", json=rpc(1, "initialize"))
    assert reply.json()["result"]["serverInfo"]["name"] == "Remote"
    assert reply.headers["mcp-session-id"] == "abc"  # the client needs this header back
    reply = harness.client.post("/mcp/demo", json=rpc(2, "tools/call", name="search",
                                                      arguments={"q": "x", "password": "p"}))
    assert reply.json()["result"]["content"][0]["text"] == "found"
    recorded = harness.spans.get_finished_spans()
    assert [span.name for span in recorded] == ["initialize", "tools/call search"]
    assert recorded[1].attributes["mcp.tool.arguments"] == '{"password": "***", "q": "x"}'


def test_notifications_get_202_and_no_span(harness):
    reply = harness.client.post("/mcp/demo", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert reply.status_code == 202 and harness.spans.get_finished_spans() == ()


def test_sse_streams_are_relayed_and_recorded(harness):
    reply = harness.client.post("/mcp/demo", json=rpc(1, "tools/call", name="stream_me", arguments={}))
    assert reply.headers["content-type"].startswith("text/event-stream")
    assert "streamed" in reply.text  # the client still receives the stream
    (span,) = harness.spans.get_finished_spans()
    assert "streamed" in span.attributes["mcp.result"]


def test_tools_list_is_captured_for_snapshots(harness):
    harness.client.post("/mcp/demo", json=rpc(1, "tools/list"))
    (span,) = harness.spans.get_finished_spans()
    assert json.loads(span.attributes["mcp.tools"])[0]["name"] == "search"


def test_session_never_stores_the_url_query(harness):
    assert harness.sessions[0].command == ["http:upstream.test/mcp"]  # ?token=SECRET is dropped


def test_unknown_server_is_404(harness):
    assert harness.client.post("/mcp/nope", json=rpc(1, "initialize")).status_code == 404


def test_batches_are_supported(harness):
    harness.client.post("/mcp/demo", json=[rpc(1, "tools/list")])  # JSON-RPC batch: a list in one POST
    assert len(harness.spans.get_finished_spans()) == 1
