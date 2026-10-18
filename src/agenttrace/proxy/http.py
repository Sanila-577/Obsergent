"""Streamable HTTP proxy: record the MCP traffic of REMOTE servers.

Same idea as the stdio proxy, different transport. MCP over Streamable HTTP is:
  * POST  each JSON-RPC message; the reply is either plain JSON or an SSE stream
          (text/event-stream) whose "data:" lines are JSON-RPC messages
  * GET   an optional SSE stream for messages the server starts
  * DELETE  ends a session

    client ──POST /mcp/<name>──► [recorder.on_request] ──POST──► real server (URL)
    client ◄─JSON or SSE──────── [recorder.on_response] ◄─────── real server

SSE (Server-Sent Events) = one long HTTP response that keeps sending lines like `data: {...json...}`.

Point the client at http://127.0.0.1:7319/mcp/<name> instead of the real URL. The
`Authorization` header is forwarded but NEVER recorded (only harmless facts decoded from a JWT:
who the caller is, see identity.py). The span logic is shared with the stdio proxy (recorder.py).

What the HTTP side adds on top of the recorder (this is what makes a gateway such as WSO2 API
Manager visible): the HTTP status and the gateway's decision (allowed / denied / unauthorized /
throttled, see gateway.py), a fingerprint of `Mcp-Session-Id`, and the trace context sent to the
gateway as a `traceparent` header so a gateway that supports it can join the same trace.
"""
# json parses request and reply bodies.
import json

# asynccontextmanager builds the startup/shutdown hook of the web app.
from contextlib import asynccontextmanager

# urlsplit cuts a URL into host, path, query.
from urllib.parse import urlsplit

# httpx is the HTTP client used to call the real server.
import httpx

# FastAPI is the web framework this proxy is built on.
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

# gateway.py: classify replies; identity.py: read JWT claims; recorder.py: make spans; sessions.py: exporter.
from agenttrace.proxy.gateway import outcome_attributes, session_hash
from agenttrace.proxy.identity import caller_attributes
from agenttrace.proxy.recorder import Recorder
from agenttrace.proxy.sessions import Session, make_provider

# Request headers worth forwarding upstream (the rest, e.g. Host, would confuse the real server).
PASS_REQUEST = ("authorization", "mcp-session-id", "mcp-protocol-version", "accept", "content-type",
                "last-event-id")
# Response headers the client needs (the session id comes back on `initialize`).
PASS_RESPONSE = ("content-type", "mcp-session-id", "mcp-protocol-version", "cache-control")


def pick_headers(headers, allowed: tuple[str, ...]) -> dict:
    """Only the headers in `allowed` (case-insensitive)."""
    return {key: value for key, value in headers.items() if key.lower() in allowed}


def adopt_trace_context(messages: list, headers) -> None:
    """If the client sent a W3C `traceparent` HTTP header, make it the parent of each request that has none."""
    # The standard header that says "I am part of trace X, span Y".
    traceparent = headers.get("traceparent")
    if not traceparent:
        return
    for message in messages:
        # Only requests (method + id) get a span.
        if isinstance(message, dict) and "method" in message and "id" in message:
            params = message.setdefault("params", {}) or {}
            message["params"] = params
            # setdefault: do not overwrite a traceparent the message already carries.
            params.setdefault("_meta", {}).setdefault("traceparent", traceparent)


def create_proxy_app(upstreams: dict[str, str], provider_factory=make_provider,
                     transport: httpx.AsyncBaseTransport | None = None,
                     verify: bool | str = True) -> FastAPI:
    """`upstreams` maps a name to the real server URL. `verify` is the TLS check of the upstream:
    True, False (dev only: self-signed certificate) or the path of a CA bundle.
    `provider_factory` and `transport` exist so tests can capture spans in memory and fake the upstream."""
    # One Recorder per named server, and the exporters to shut down at the end.
    recorders: dict[str, Recorder] = {}
    providers = []
    for name, url in upstreams.items():
        parts = urlsplit(url)  # keep only host + path in the session: the query may hold a token
        # A session identifies this proxy's connection to that server.
        session = Session(server_name=name, command=[f"http:{parts.netloc}{parts.path}"])
        provider = provider_factory(session)
        providers.append(provider)
        recorders[name] = Recorder(provider.get_tracer("agenttrace.proxy"), name)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Runs at startup: create the shared HTTP client.
        app.state.client = httpx.AsyncClient(timeout=None, transport=transport, verify=verify)  # one shared client
        yield
        # Runs at shutdown: close the client and flush the last spans.
        await app.state.client.aclose()
        for provider in providers:
            provider.shutdown()  # send the last batch of spans

    # The web app; the three routes below are attached to it.
    app = FastAPI(title="AgentTrace HTTP proxy", lifespan=lifespan)

    def url_of(name: str) -> str:
        # 404 if the client asked for a server name we do not know.
        if name not in upstreams:
            raise HTTPException(404, f"unknown MCP server '{name}'")
        return upstreams[name]

    async def open_upstream(request: Request, method: str, url: str, extra_headers: dict | None = None,
                            **kwargs) -> httpx.Response:
        """Send the request upstream and keep the response open for streaming."""
        client: httpx.AsyncClient = request.app.state.client
        # Forward only the allowed headers, plus any extras (like traceparent).
        headers = pick_headers(request.headers, PASS_REQUEST) | (extra_headers or {})
        # stream=True: do not download the whole reply first; SSE may never end.
        return await client.send(client.build_request(method, url, headers=headers, **kwargs), stream=True)

    async def relay_stream(upstream: httpx.Response, on_line=None, on_close=None):
        """Yield the upstream body line by line, letting `on_line` look at each line."""
        try:
            async for line in upstream.aiter_lines():
                if on_line:
                    on_line(line)
                # Pass the line on to the client.
                yield line + "\n"
        finally:
            # Always release the connection, and let the caller finish unanswered spans.
            await upstream.aclose()
            if on_close:
                on_close()

    # POST /mcp/<name>: the main route; every JSON-RPC message from the client arrives here.
    @app.post("/mcp/{name}")
    async def forward(name: str, request: Request):
        url, recorder = url_of(name), recorders[name]
        # The request body is JSON: one message, or a list (batch).
        body = await request.json()
        messages = body if isinstance(body, list) else [body]  # JSON-RPC allows batches
        adopt_trace_context(messages, request.headers)
        # Ids of the requests in this POST (notifications have no id).
        sent_ids = [m["id"] for m in messages if isinstance(m, dict) and "method" in m and "id" in m]

        # Who is calling and in which MCP session: harmless facts only, never the token or the raw session id.
        request_session = request.headers.get("mcp-session-id")
        about_caller = caller_attributes(request.headers.get("authorization"))
        if request_session:
            about_caller["mcp.session.hash"] = session_hash(request_session)
        proxy_traceparent = None
        for message in messages:
            if isinstance(message, dict):
                recorder.on_request(message, extra=about_caller)  # starts spans + adds the trace id to _meta
                meta = (message.get("params") or {}).get("_meta", {})
                # Remember the first traceparent to also send as an HTTP header.
                proxy_traceparent = proxy_traceparent or meta.get("traceparent")
        # Send the proxy span's trace context to the gateway as an HTTP header too.
        upstream = await open_upstream(request, "POST", url, json=body,
                                       extra_headers={"traceparent": proxy_traceparent} if proxy_traceparent else None)
        headers = pick_headers(upstream.headers, PASS_RESPONSE)
        status = upstream.status_code
        # `initialize` creates the session: its id comes back in the reply, later calls send it themselves.
        session_id = upstream.headers.get("mcp-session-id") or request_session
        activity_id = upstream.headers.get("activityid")  # WSO2 API Manager's correlation id for this call

        def outcome(message: dict | None) -> dict:
            """Span attributes for this HTTP reply (status, gateway decision, session, correlation id)."""
            return outcome_attributes(status, message, session_id, activity_id)

        # Case 1: the reply is an SSE stream.
        if upstream.headers.get("content-type", "").startswith("text/event-stream"):
            def record_event(line: str) -> None:  # each SSE "data:" line is one JSON-RPC message
                if line.startswith("data:"):
                    try:
                        # Drop the "data:" prefix (5 chars) and parse the JSON.
                        message = json.loads(line[5:])
                    except json.JSONDecodeError:
                        return  # keep-alive or non-JSON event: just relay it
                    recorder.on_response(message, extra=outcome(message))

            def close_unanswered() -> None:
                # The stream ended: any request without an answer is closed as an error.
                recorder.close_ids(sent_ids, "stream ended without a response",
                                   extra=outcome(None))

            return StreamingResponse(relay_stream(upstream, record_event, close_unanswered), status_code=status,
                                     headers=headers, media_type="text/event-stream")

        # Case 2: a plain reply. Read it fully.
        raw = await upstream.aread()  # plain JSON (or an empty 202 for notifications)
        await upstream.aclose()
        if raw:
            try:
                data = json.loads(raw)
                # The reply may be one message or a batch.
                for message in (data if isinstance(data, list) else [data]):
                    if isinstance(message, dict):
                        recorder.on_response(message, extra=outcome(message))
            except json.JSONDecodeError:
                pass  # not JSON (e.g. an HTML error page): pass it on untouched
        # Requests that got no JSON-RPC answer (a 401 page, a 429...) still get an outcome on their span.
        recorder.close_ids(sent_ids, f"no JSON-RPC response (HTTP {status})",
                           extra=outcome(None))
        # Hand the unchanged reply back to the client.
        return Response(raw, status_code=status, headers=headers)

    # GET /mcp/<name>: the optional server-to-client stream.
    @app.get("/mcp/{name}")
    async def listen(name: str, request: Request):
        """The optional server->client SSE stream: relayed untouched (server-started messages aren't recorded)."""
        upstream = await open_upstream(request, "GET", url_of(name))
        return StreamingResponse(relay_stream(upstream), status_code=upstream.status_code,
                                 headers=pick_headers(upstream.headers, PASS_RESPONSE))

    # DELETE /mcp/<name>: the client ends its MCP session.
    @app.delete("/mcp/{name}")
    async def end_session(name: str, request: Request):
        upstream = await open_upstream(request, "DELETE", url_of(name))
        body = await upstream.aread()
        await upstream.aclose()
        return Response(body, status_code=upstream.status_code,
                        headers=pick_headers(upstream.headers, PASS_RESPONSE))

    return app
