"""The WSO2 API Platform gateway (Envoy router + policy engine): its spans, recorded from a real gateway 1.2.1.

tests/fixtures/api_platform_gateway.json holds three traces captured through `agenttrace proxy-http`:
a tools/list, an allowed tools/call, and a tools/call the `mcp-acl-list` policy refused (HTTP 400, JSON-RPC code -32000).
Every gateway span is stored with its original attributes (the gateway.* ones are added at ingest).
"""
import pytest

from agenttrace.analysis.gateway_view import summarize_gateway
from agenttrace.ingest.gateway import is_gateway_span, normalize_gateway_spans, platform_phase
from agenttrace.proxy.gateway import classify
from conftest import load_fixture_spans

FIXTURE = "api_platform_gateway.json"


@pytest.fixture
def spans():
    loaded = load_fixture_spans(FIXTURE)
    normalize_gateway_spans(loaded)
    return loaded


def test_router_and_policy_engine_spans_are_gateway_spans(spans):
    gateway = [s for s in spans if s.service in ("router", "policy-engine")]
    assert gateway and all(is_gateway_span(s) for s in gateway)
    assert all(s.attributes["agenttrace.layer"] == "gateway" for s in gateway)
    assert not any("agenttrace.layer" in s.attributes for s in spans if s.service == "agenttrace-proxy")


def test_phases_are_backend_and_policy_engine(spans):
    phases = {s.attributes["gateway.phase"] for s in spans if "gateway.phase" in s.attributes}
    assert phases == {"backend", "policy_engine"}
    named = {s.name: platform_phase(s) for s in spans if s.service in ("router", "policy-engine")}
    assert named["external_processing.process"] == "policy_engine"
    assert named["external_processing.process_request_headers"] is None  # children are not counted twice


def test_the_ingress_span_is_the_call_and_carries_status_and_decision(spans):
    calls = [s for s in spans if "gateway.activity_id" in s.attributes]
    assert {c.attributes["gateway.decision"] for c in calls} == {"allowed", "error"}  # 400: only the proxy sees why
    refused = next(c for c in calls if c.attributes["gateway.status"] == 400)
    assert refused.status_code == "ERROR" and "400" in refused.status_message


def test_gateway_spans_join_the_proxy_trace(spans):
    for trace_id in {s.trace_id for s in spans}:
        in_trace = [s for s in spans if s.trace_id == trace_id]
        roots = [s for s in in_trace if s.parent_span_id is None]
        assert len(roots) == 1 and roots[0].service == "agenttrace-proxy"  # the gateway continued the traceparent


def test_summary_matches_gateway_calls_to_proxy_calls_and_uses_the_specific_decision(spans):
    gateway = [s for s in spans if s.attributes.get("agenttrace.layer") == "gateway"]
    proxy = [s for s in spans if s.attributes.get("gateway.decision") and "agenttrace.layer" not in s.attributes]
    summary = summarize_gateway(gateway, proxy)
    assert summary["calls_total"] == 3
    assert summary["decisions"] == {"allowed": 2, "denied": 1}  # the proxy saw -32000 "not allowed"
    assert set(summary["phases"]) == {"backend", "policy_engine"}
    assert summary["by_tool"]["get_price_and_stock"] == {"denied": 1}
    assert all(c["correlation"] == "trace" for c in summary["calls"])


def test_the_denied_answer_is_classified_from_the_json_rpc_body():
    refusal = {"error": {"code": -32000, "message": "MCP capability not allowed"}, "id": 5, "jsonrpc": "2.0"}
    assert classify(400, refusal) == "denied"
