> **Two products, two sections.** The first section is the **WSO2 API Platform gateway** (Docker), the one the README and
> [wso2-integration.md](wso2-integration.md) use. The second, further down, is **WSO2 API Manager 4.7** (the Java product),
> kept as an earlier experiment.

## WSO2 API Platform gateway 1.2.1 (Docker): what was observed

Run on 18 Oct 2026 with `gateway/docker-compose.yaml` and the commands in [wso2-integration.md](wso2-integration.md).

| Question | Observation |
|---|---|
| Register an MCP server | `POST :9090/api/management/v1/mcp-proxies` with basic auth, 201; `PUT .../mcp-proxies/<name>` updates (200). Config applies within ~3 s |
| Where is it served | `http://localhost:8080/<context>/mcp`. The gateway sends the request to **exactly** the configured upstream URL (the context is replaced, `/mcp` is not appended), so the upstream must be `.../mcp` (`[mcp] append_resource_path_to_backend = false`) |
| MCP session | `Mcp-Session-Id` passes through unchanged |
| Allowed call | HTTP 200, SSE or JSON body passed through; spans below |
| Refused tool (`mcp-acl-list`, mode deny) | **HTTP 400** with `{"error":{"code":-32000,"message":"MCP capability not allowed"},"id":N,"jsonrpc":"2.0"}`: AgentTrace classifies it `denied` |
| `tools/list` | The gateway **removes denied tools** from the list (the agent never sees them): AgentTrace shows `tool_removed` |
| Trace propagation | The router **continues the `traceparent`** the proxy sends: the proxy span is the parent of the gateway's `ingress` span, so agent, proxy and gateway are one trace |
| Correlation header | None (no `activityid`): AgentTrace joins by trace / parent span |
| Telemetry | `[tracing]` in `gateway/configs/config.toml`, **OTLP/gRPC** (default port 4317), services `router` and `policy-engine` |

Span tree of one call:

```
tools/call search_books                      [agenttrace-proxy]
└─ ingress                                   [router]         http.status_code, http.route, guid:x-request-id
   ├─ async ...ExternalProcessor.Process egress   [router]
   │  └─ external_processing.process        [policy-engine]  api_name, api_version, route_name
   │     ├─ external_processing.process_request_headers / _body
   │     ├─ policy.request.<policy>  (policy.execution_time_ns)
   │     └─ external_processing.process_response_headers / _body, policy.response.<policy>
   └─ router upstream_<host>_<port> egress  [router]         the MCP server (backend)
```

Mapping (`ingest/gateway.py`): `ingress` is the call (`gateway.activity_id` = its request id, `gateway.status`,
`gateway.decision` from the status); `external_processing.process` is phase `policy_engine`, the upstream egress is phase
`backend`. Not yet verified: 401/403 (needs `mcp-auth`, which needs an identity provider), 429 (`mcp-ratelimit`).

# Earlier experiment: WSO2 API Manager 4.7 MCP gateway, what was verified

These notes come from a real run, not from the documentation: **WSO2 API Manager 4.7.0** (build 4.7.0.19, Java 21)
running locally, an upstream MCP server (`examples/bookshop/bookshop_http.py`) behind its MCP gateway, and AgentTrace
in front of and beside it. Everything below was observed unless it says "not verified".

## How an MCP server gets into the gateway

APIM's Publisher REST API has full MCP support (`/api/am/publisher/v4/mcp-servers/...`), so nothing needs clicking:

1. `POST /mcp-servers/validate-mcp-server` with the upstream's **base** URL returns the upstream's tools.
2. `POST /mcp-servers/generate-from-mcp-server` creates the MCP server. The request must carry `gatewayType`
   (`wso2/synapse`), `policies` (`["Unlimited"]`) and `operations`, where each tool is
   `{description, feature: "TOOL", backendOperationMapping: {backendOperation: {target: <tool name>, verb: "TOOL"}}}`.
   Leaving those out gives a bare HTTP 500 ("no URI templates were produced"). The Publisher's own source
   (shipped in the product under `webapps/publisher/source`) shows the exact payload.
3. Per-tool scopes: `PUT /mcp-servers/{id}` with `scopes` and `operations[].scopes`. Scope names must be unique
   across all APIs in the installation.
4. `POST .../revisions`, `POST .../deploy-revision` (vhost `localhost`, gateway `Default`), then
   `POST /mcp-servers/change-lifecycle?action=Publish`.
5. Developer Portal: create an application, subscribe it (`/subscriptions` with the MCP server's id as `apiId`),
   generate keys, use the client-credentials grant for an access token.

(The script that did this for APIM 4.7 was removed: `scripts/wso2_gateway.py` now targets the API Platform gateway.)

## What the gateway looks like from outside

| Fact | Observed |
|---|---|
| Endpoint you give APIM | The upstream's **base** URL. APIM appends `/mcp` itself (giving the full URL gave `/mcp/mcp`, a 404) |
| Invoke URL | `https://localhost:8243/<context>/<version>/mcp` (HTTP: `http://localhost:8280/...`) |
| TLS | Self-signed certificate: use `agenttrace proxy-http --insecure` (dev) or `--ca-bundle` |
| Credentials | `Authorization: Bearer <JWT>`; the JWT claims are `sub`, `aut` (APPLICATION), `iss`, `client_id`, `azp`, `aud`, `scope`. **There is no application name claim**: the caller is identified by `client_id` (the application's consumer key) |
| Session | `Mcp-Session-Id` from the upstream's `initialize` reply is passed through; calls without it get the upstream's HTTP 400 `{"error":{"code":-32600,"message":"Bad Request: Missing session ID"}}` |
| Response headers | **`activityid`** on every response: APIM's correlation id for that call |
| `tools/list` | Answered as plain JSON; `initialize` and `tools/call` stream back from the upstream as `text/event-stream` |
| Authentication | `tools/call` needs a token (`401`); `tools/list` was answered without one |

### Refusals

| Case | HTTP | Body |
|---|---|---|
| No token | 401 | `{"code":"900902","message":"Missing Credentials",...}` and `WWW-Authenticate: Bearer resource_metadata=..., error="invalid_token"` |
| Bad token | 401 | `{"code":"900901","message":"Invalid Credentials",...}` |
| Token without the tool's scope | 403 | `{"code":"900910","message":"The access token does not allow you to access the requested resource","description":"User is NOT authorized to access the Resource: <tool>. Scope validation failed."}` |
| Rate limit | 429 | **not verified**: a throttling policy was created but did not take effect in the test; AgentTrace classifies 429 as `throttled` from the HTTP status alone |

AgentTrace turns these into one `gateway.decision` per call: `allowed`, `unauthorized` (401), `forbidden` (403),
`throttled` (429), `denied` (an access-control policy answer, JSON-RPC `-32000` "MCP capability not allowed"; that
shape is from WSO2's API Platform documentation and was **not verified** on APIM 4.7), or `error`.

## Telemetry

* APIM exports OpenTelemetry with `[apim.open_telemetry] remote_tracer.name = "otlp"` and a `remote_tracer.url`.
  **It speaks OTLP over gRPC, not HTTP**: pointing it at AgentTrace's HTTP endpoint fails with an HTTP/2 error.
  Hence `agenttrace up --grpc` (port 4317) and `remote_tracer.url = "http://localhost:4317"`.
* Service name of its spans: `API:Gateway`. Per call: `<API>--<version>--<tenant>` (tags `span.activity.id`,
  `span.api.name`, `span.http.response.status.code`, `span.consumerkey`, `span.request.path`...), `POST--/mcp`, and one
  span per phase: `API:CORS_Request_Latency`, `API:Key_Validation_Latency`, `API:Throttle_Latency`,
  `API:Google_Analytics_Latency`, `API:Request_Mediation_Latency`, `API:Backend_Latency`, `API:Response_Mediation_Latency`.
* **APIM continues an incoming W3C `traceparent`.** AgentTrace's HTTP proxy sends its span's `traceparent` as an HTTP
  header, so the gateway's spans become children of the proxy span in the same trace.
* `span.activity.id` equals the `activityid` response header exactly, so a gateway call can be matched to the call that
  caused it even without a shared trace (`correlation: activity` in the API).
* APIM leaves the span status "unset" even for a 401/403; AgentTrace marks refused calls as errors.

## Not verified

* The 429 response and `Retry-After` behaviour.
* The `denied` shape (MCP Access Control policy) on APIM 4.7: it belongs to WSO2's newer API Platform gateway.
* `Mcp-Session-Id` handling when several clients share one gateway (the session id is the upstream's).
* APIM 4.6 (the version the plan was first written for): everything above was observed on 4.7.0.
