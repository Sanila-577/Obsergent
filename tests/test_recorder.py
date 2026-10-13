"""The Recorder turns MCP messages into spans. No processes, no network: feed it dicts."""
import json

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agenttrace.proxy.recorder import SESSION_ENV, Recorder

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN_ID = "00f067aa0ba902b7"


def make_recorder(monkeypatch, **env):
    for k in ("TRACEPARENT", SESSION_ENV):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    mem = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(mem))
    return Recorder(provider.get_tracer("t"), "demo"), mem


def request(msg_id=1, method="tools/call", **params):
    return {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}


def test_request_and_response_make_one_span(monkeypatch):
    rec, mem = make_recorder(monkeypatch)
    rec.on_request(request(name="search", arguments={"q": "python", "api_key": "SECRET"}))
    assert mem.get_finished_spans() == ()  # still open: no answer yet
    rec.on_response({"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "hi"}]}})
    (span,) = mem.get_finished_spans()
    assert span.name == "tools/call search"
    assert span.attributes["gen_ai.tool.name"] == "search"
    assert span.attributes["mcp.tool.arguments"] == '{"api_key": "***", "q": "python"}'  # secret hidden
    assert "hi" in span.attributes["mcp.result"]


def test_notifications_and_unknown_responses_are_ignored(monkeypatch):
    rec, mem = make_recorder(monkeypatch)
    note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert rec.on_request(note) == note
    stray = {"jsonrpc": "2.0", "id": 99, "result": {}}
    assert rec.on_response(stray) == stray
    assert mem.get_finished_spans() == ()


def test_error_responses_mark_the_span(monkeypatch):
    rec, mem = make_recorder(monkeypatch)
    rec.on_request(request(1, name="x"))
    rec.on_response({"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "bad params"}})
    rec.on_request(request(2, name="y"))
    rec.on_response({"jsonrpc": "2.0", "id": 2, "result": {"isError": True, "content": []}})
    first, second = mem.get_finished_spans()
    assert first.status.status_code.name == "ERROR" and first.attributes["mcp.error.code"] == -32602
    assert second.status.status_code.name == "ERROR"


def test_unanswered_requests_are_closed_as_errors(monkeypatch):
    rec, mem = make_recorder(monkeypatch)
    rec.on_request(request(1, name="x"))
    rec.close_pending()
    (span,) = mem.get_finished_spans()
    assert span.status.status_code.name == "ERROR"


def test_traceparent_in_meta_makes_the_span_a_child_and_is_rewritten(monkeypatch):
    rec, mem = make_recorder(monkeypatch)
    msg = request(name="x", _meta={"traceparent": f"00-{TRACE_ID}-{SPAN_ID}-01"})
    out = rec.on_request(msg)
    rec.on_response({"id": 1, "result": {}})
    (span,) = mem.get_finished_spans()
    assert format(span.context.trace_id, "032x") == TRACE_ID  # joined the agent's trace
    assert format(span.parent.span_id, "016x") == SPAN_ID  # child of the agent's tool step
    # ...and the server now sees the PROXY span as its parent, not the agent's span
    assert out["params"]["_meta"]["traceparent"].split("-")[2] == format(span.context.span_id, "016x")


def test_generic_TRACEPARENT_is_ignored_regression(monkeypatch):
    """The lesson from the plan: another tool set TRACEPARENT (not sampled) and the proxy recorded nothing."""
    rec, mem = make_recorder(monkeypatch, TRACEPARENT=f"00-{TRACE_ID}-{SPAN_ID}-00")
    rec.on_request(request(name="x"))
    rec.on_response({"id": 1, "result": {}})
    (span,) = mem.get_finished_spans()  # still recorded...
    assert format(span.context.trace_id, "032x") != TRACE_ID  # ...in its OWN trace, not the stray one


def test_session_parent_from_MCP_PROXY_TRACEPARENT(monkeypatch):
    rec, mem = make_recorder(monkeypatch, **{SESSION_ENV: f"00-{TRACE_ID}-{SPAN_ID}-01"})
    rec.on_request(request(1, method="initialize"))  # no _meta: uses the session parent
    rec.on_response({"id": 1, "result": {}})
    (span,) = mem.get_finished_spans()
    assert format(span.context.trace_id, "032x") == TRACE_ID


def test_tools_list_result_is_kept_in_full(monkeypatch):
    rec, mem = make_recorder(monkeypatch)
    tools = [{"name": f"t{i}", "description": "d" * 500, "inputSchema": {}} for i in range(20)]  # > 4000 chars
    rec.on_request(request(1, method="tools/list"))
    rec.on_response({"id": 1, "result": {"tools": tools}})
    (span,) = mem.get_finished_spans()
    assert json.loads(span.attributes["mcp.tools"]) == tools
