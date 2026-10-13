"""The Streamable HTTP proxy, with a fake upstream MCP server (httpx.MockTransport)."""
import json

import httpx
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agenttrace.proxy.http import create_proxy_app
from agenttrace.proxy.sessions import Session

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


def make_client():
    mem = InMemorySpanExporter()
    sessions: list[Session] = []

    def factory(session):  # capture spans in memory instead of sending them anywhere
        sessions.append(session)
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(mem))
        return provider

    app = create_proxy_app({"demo": UPSTREAM}, provider_factory=factory, transport=httpx.MockTransport(fake_upstream))
    return TestClient(app), mem, sessions


def rpc(msg_id, method, **params):
    return {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}


def test_json_responses_are_recorded_and_forwarded_unchanged():
    client, mem, _ = make_client()
    with client:
        r = client.post("/mcp/demo", json=rpc(1, "initialize"))
        assert r.json()["result"]["serverInfo"]["name"] == "Remote"
        assert r.headers["mcp-session-id"] == "abc"  # the client needs this header back
        r = client.post("/mcp/demo", json=rpc(2, "tools/call", name="search", arguments={"q": "x", "password": "p"}))
        assert r.json()["result"]["content"][0]["text"] == "found"
    names = [s.name for s in mem.get_finished_spans()]
    assert names == ["initialize", "tools/call search"]
    call = mem.get_finished_spans()[1]
    assert call.attributes["mcp.tool.arguments"] == '{"password": "***", "q": "x"}'


def test_notifications_get_202_and_no_span():
    client, mem, _ = make_client()
    with client:
        r = client.post("/mcp/demo", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202 and mem.get_finished_spans() == ()


def test_sse_streams_are_relayed_and_recorded():
    client, mem, _ = make_client()
    with client:
        r = client.post("/mcp/demo", json=rpc(1, "tools/call", name="stream_me", arguments={}))
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "streamed" in r.text  # the client still receives the stream
    (span,) = mem.get_finished_spans()
    assert "streamed" in span.attributes["mcp.result"]


def test_tools_list_is_captured_for_snapshots():
    client, mem, _ = make_client()
    with client:
        client.post("/mcp/demo", json=rpc(1, "tools/list"))
    (span,) = mem.get_finished_spans()
    assert json.loads(span.attributes["mcp.tools"])[0]["name"] == "search"


def test_session_never_stores_the_url_query():
    _, _, sessions = make_client()
    assert sessions[0].command == ["http:upstream.test/mcp"]  # ?token=SECRET is dropped


def test_unknown_server_is_404():
    client, _, _ = make_client()
    with client:
        assert client.post("/mcp/nope", json=rpc(1, "initialize")).status_code == 404


def test_batches_are_supported():
    client, mem, _ = make_client()
    with client:
        # JSON-RPC batch: a list of messages in one POST
        client.post("/mcp/demo", json=[rpc(1, "tools/list")])
    assert len(mem.get_finished_spans()) == 1
