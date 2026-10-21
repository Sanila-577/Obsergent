"""WSO2 API Manager MCP gateway support: who called, what the gateway decided, gateway telemetry.

The shapes used here were captured from a REAL APIM 4.7 gateway:
401 bodies (codes 900901/900902), the 403 for a missing tool scope (900910), the `activityid`
response header, the JWT claims, and the gateway's own OpenTelemetry spans (tests/fixtures/apim_gateway.json).
"""
import base64
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from obsergent.cli import build_parser
from obsergent.ingest.gateway import normalize_gateway_spans, phase_of
from obsergent.models import Span
from obsergent.proxy.gateway import classify, outcome_attributes, session_hash
from obsergent.proxy.http import create_proxy_app
from obsergent.proxy.identity import caller_attributes

FIXTURE = Path(__file__).parent / "fixtures" / "apim_gateway.json"


def make_jwt(**claims) -> str:
    """An unsigned JWT-shaped token (header.payload.signature) with the given claims."""
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{part({'alg': 'none'})}.{part(claims)}.signature"


# ----------------------------------------------------------------------------- who is calling
def test_caller_attributes_from_an_apim_style_token():
    token = make_jwt(sub="4edd01fa", client_id="CONSUMER-KEY", azp="CONSUMER-KEY", iss="https://localhost:9443/oauth2/token",
                     aud="CONSUMER-KEY", scope="default stock:read", application={"name": "obsergent-agent"})
    attributes = caller_attributes(f"Bearer {token}")
    assert attributes["obsergent.caller.client_id"] == "CONSUMER-KEY"
    assert attributes["obsergent.caller.sub"] == "4edd01fa"
    assert attributes["obsergent.caller.scopes"] == "default stock:read"
    assert attributes["obsergent.caller.application"] == "obsergent-agent"
    assert token not in json.dumps(attributes)  # the token itself is never part of the result


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer opaque-no-dots", "Bearer a.b.c", "Bearer"])
def test_unreadable_credentials_give_no_attributes(header):
    assert caller_attributes(header) == {}


def test_list_valued_claims_are_flattened():
    attributes = caller_attributes("Bearer " + make_jwt(aud=["a", "b"], scp=["x", "y"]))
    assert attributes["obsergent.caller.audience"] == "a,b" and attributes["obsergent.caller.scopes"] == "x y"


# ------------------------------------------------------------------- what the gateway decided
@pytest.mark.parametrize("status, message, expected", [
    (200, {"result": {}}, "allowed"),
    (401, None, "unauthorized"),
    (403, None, "forbidden"),
    (429, None, "throttled"),
    (400, {"error": {"code": -32000, "message": "MCP capability not allowed"}}, "denied"),
    (400, {"error": {"code": -32600, "message": "Bad Request: Missing session ID"}}, "error"),
    (200, {"error": {"code": -32602, "message": "bad params"}}, "error"),
    (500, None, "error"),
])
def test_gateway_decision_classification(status, message, expected):
    assert classify(status, message) == expected


def test_session_fingerprint_is_stable_short_and_not_the_id():
    assert session_hash("496fcb4acb9546cf8de64d72fa019c86") == session_hash("496fcb4acb9546cf8de64d72fa019c86")
    assert len(session_hash("x")) == 12 and "496fcb" not in session_hash("496fcb4acb9546cf8de64d72fa019c86")
    assert session_hash(None) is None


def test_outcome_attributes_include_the_activity_id():
    attributes = outcome_attributes(403, None, "sid", "activity-1")
    assert attributes["http.response.status_code"] == 403 and attributes["gateway.decision"] == "forbidden"
    assert attributes["gateway.activity_id"] == "activity-1" and "mcp.session.hash" in attributes


# ------------------------------------------------- the HTTP proxy in front of a fake APIM gateway
TOKEN = make_jwt(sub="s1", client_id="CK-1", scope="default")
ACTIVITY = "6ef66226-c284-4533-bab5-cf125b726b2d"


class FakeGateway:
    """Behaves like the real APIM gateway did: bearer auth, per-tool scope, `activityid` + session headers."""

    def __init__(self):
        self.seen_traceparents = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen_traceparents.append(request.headers.get("traceparent"))
        message = json.loads(request.content)
        headers = {"activityid": ACTIVITY}
        if "id" not in message:
            return httpx.Response(202, headers=headers)
        if message["method"] == "initialize":
            body = {"jsonrpc": "2.0", "id": message["id"], "result": {"serverInfo": {"name": "Bookshop"}}}
            return httpx.Response(200, json=body, headers=headers | {"mcp-session-id": "496fcb4acb9546cf"})
        if message["method"] == "tools/call":
            if "authorization" not in request.headers:  # real body of APIM's code 900902
                return httpx.Response(401, json={"code": "900902", "message": "Missing Credentials"}, headers=headers)
            if message["params"]["name"] == "get_price_and_stock":  # per-tool scope, real body of code 900910
                return httpx.Response(403, json={"code": "900910", "message": "The access token does not allow you "
                                                 "to access the requested resource"}, headers=headers)
            result = {"content": [{"type": "text", "text": "ok"}]}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result}, headers=headers)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": {}}, headers=headers)


@pytest.fixture
def gateway_proxy():
    gateway, spans = FakeGateway(), InMemorySpanExporter()

    def provider_factory(session):
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(spans))
        return provider

    app = create_proxy_app({"wso2": "https://gateway.test/bookshop/1.0.0/mcp"}, provider_factory=provider_factory,
                           transport=httpx.MockTransport(gateway))
    with TestClient(app) as client:
        yield client, gateway, spans


def rpc(msg_id, method, **params):
    return {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}


def by_name(spans, name):
    return next(s for s in spans.get_finished_spans() if s.name == name)


def test_decisions_activity_ids_and_caller_are_recorded(gateway_proxy):
    client, gateway, spans = gateway_proxy
    auth = {"authorization": f"Bearer {TOKEN}"}
    client.post("/mcp/wso2", json=rpc(1, "initialize"), headers=auth)
    session = {"mcp-session-id": "496fcb4acb9546cf"}
    assert client.post("/mcp/wso2", json=rpc(2, "tools/call", name="search_books", arguments={}),
                       headers=auth | session).status_code == 200
    assert client.post("/mcp/wso2", json=rpc(3, "tools/call", name="get_price_and_stock", arguments={}),
                       headers=auth | session).status_code == 403
    assert client.post("/mcp/wso2", json=rpc(4, "tools/call", name="search_books", arguments={}),
                       headers=session).status_code == 401  # no token

    allowed, forbidden = by_name(spans, "tools/call search_books"), by_name(spans, "tools/call get_price_and_stock")
    assert allowed.attributes["gateway.decision"] == "allowed"
    assert allowed.attributes["http.response.status_code"] == 200
    assert forbidden.attributes["gateway.decision"] == "forbidden" and forbidden.status.status_code.name == "ERROR"
    unauthorized = next(s for s in spans.get_finished_spans()
                        if s.attributes.get("gateway.decision") == "unauthorized")
    assert unauthorized.attributes["http.response.status_code"] == 401
    assert unauthorized.status.status_code.name == "ERROR"
    assert allowed.attributes["gateway.activity_id"] == ACTIVITY  # APIM's correlation id
    assert allowed.attributes["obsergent.caller.client_id"] == "CK-1"
    assert "obsergent.caller.client_id" not in unauthorized.attributes  # no token, no identity
    assert allowed.attributes["mcp.session.hash"] == by_name(spans, "initialize").attributes["mcp.session.hash"]


def test_the_token_and_raw_session_id_are_never_recorded(gateway_proxy):
    client, gateway, spans = gateway_proxy
    auth = {"authorization": f"Bearer {TOKEN}", "mcp-session-id": "496fcb4acb9546cf"}
    client.post("/mcp/wso2", json=rpc(1, "initialize"), headers=auth)
    client.post("/mcp/wso2", json=rpc(2, "tools/call", name="search_books", arguments={}), headers=auth)
    everything = json.dumps([dict(s.attributes) for s in spans.get_finished_spans()])
    assert TOKEN not in everything and TOKEN.split(".")[2] not in everything
    assert "496fcb4acb9546cf" not in everything


def test_the_trace_context_is_sent_to_the_gateway_as_a_header(gateway_proxy):
    client, gateway, spans = gateway_proxy
    client.post("/mcp/wso2", json=rpc(1, "tools/call", name="search_books", arguments={}),
                headers={"authorization": f"Bearer {TOKEN}"})
    sent = gateway.seen_traceparents[-1]
    call = by_name(spans, "tools/call search_books")
    assert sent is not None
    _, trace_id, span_id, _ = sent.split("-")
    assert trace_id == format(call.context.trace_id, "032x") and span_id == format(call.context.span_id, "016x")


def test_a_traceparent_from_the_client_becomes_the_parent(gateway_proxy):
    client, gateway, spans = gateway_proxy
    client.post("/mcp/wso2", json=rpc(1, "tools/call", name="search_books", arguments={}),
                headers={"authorization": f"Bearer {TOKEN}",
                         "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"})
    call = by_name(spans, "tools/call search_books")
    assert format(call.context.trace_id, "032x") == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert format(call.parent.span_id, "016x") == "00f067aa0ba902b7"


def test_proxy_http_tls_options_exist():
    args = build_parser().parse_args(["proxy-http", "--name", "w", "--url", "https://x", "--ca-bundle", "ca.pem"])
    assert args.ca_bundle == "ca.pem" and args.insecure is False
    assert build_parser().parse_args(["proxy-http", "--name", "w", "--url", "https://x", "--insecure"]).insecure


# ---------------------------------------------------------- the gateway's own telemetry (real APIM spans)
def load_fixture() -> list[Span]:
    return [Span(**row) for row in json.loads(FIXTURE.read_text())]


def test_phase_names():
    assert phase_of("API:Key_Validation_Latency") == "key_validation"
    assert phase_of("API:Backend_Latency") == "backend" and phase_of("POST--/mcp") is None


def test_real_apim_spans_are_normalized():
    spans = load_fixture()
    normalize_gateway_spans(spans)
    gateway = [s for s in spans if s.attributes.get("obsergent.layer") == "gateway"]
    assert gateway and {s.service for s in gateway} == {"API:Gateway"}
    phases = {s.attributes["gateway.phase"] for s in gateway if "gateway.phase" in s.attributes}
    assert {"key_validation", "backend", "request_mediation", "response_mediation"} <= phases
    calls = [s for s in gateway if "gateway.activity_id" in s.attributes]
    assert {c.attributes["gateway.decision"] for c in calls} == {"allowed", "forbidden", "unauthorized"}
    allowed = next(c for c in calls if c.attributes["gateway.decision"] == "allowed")
    assert allowed.attributes["gateway.api"] == "BookshopMCP" and allowed.attributes["gateway.status"] == 200
    assert allowed.attributes["gateway.consumer_key"] and allowed.attributes["gateway.path"] == "bookshop/1.0.0/mcp"
    assert allowed.status_code == "UNSET"
    refused = [c for c in calls if c.attributes["gateway.decision"] != "allowed"]
    assert all(c.status_code == "ERROR" and "gateway: HTTP" in c.status_message for c in refused)  # APIM says UNSET
    spans_without_gateway_layer = [s for s in spans if s not in gateway]
    assert all("obsergent.layer" not in s.attributes for s in spans_without_gateway_layer)  # proxy spans untouched


def test_gateway_and_proxy_spans_form_one_trace_and_share_the_activity_id():
    spans = load_fixture()
    normalize_gateway_spans(spans)
    proxy_call = next(s for s in spans if s.service == "obsergent-proxy" and s.name == "tools/call search_books")
    call_at_gateway = next(s for s in spans if s.attributes.get("obsergent.layer") == "gateway"
                           and s.attributes.get("gateway.decision") == "allowed")
    assert call_at_gateway.trace_id == proxy_call.trace_id  # APIM continued the proxy's traceparent
    assert call_at_gateway.parent_span_id == proxy_call.span_id  # ...as a child of the proxy's span
    assert call_at_gateway.attributes["gateway.activity_id"] == proxy_call.attributes["gateway.activity_id"]
