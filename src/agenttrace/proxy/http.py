"""Streamable HTTP proxy: record the MCP traffic of REMOTE servers.

Same idea as the stdio proxy, different transport. MCP over Streamable HTTP is:
  * POST  each JSON-RPC message; the reply is either plain JSON or an SSE stream
          (text/event-stream) whose "data:" lines are JSON-RPC messages
  * GET   an optional SSE stream for messages the server starts
  * DELETE  ends a session

    client ──POST /mcp/<name>──► [recorder.on_request] ──POST──► real server (URL)
    client ◄─JSON or SSE──────── [recorder.on_response] ◄─────── real server

Point the client at http://127.0.0.1:7319/mcp/<name> instead of the real URL. The
`Authorization` header is forwarded but NEVER recorded. The span logic is shared
with the stdio proxy (recorder.py).
"""
import json
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

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


def create_proxy_app(upstreams: dict[str, str], provider_factory=make_provider,
                     transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """`upstreams` maps a name to the real server URL. `provider_factory` and `transport`
    exist so tests can capture spans in memory and fake the upstream server."""
    recorders: dict[str, Recorder] = {}
    providers = []
    for name, url in upstreams.items():
        parts = urlsplit(url)  # keep only host + path in the session: the query may hold a token
        session = Session(server_name=name, command=[f"http:{parts.netloc}{parts.path}"])
        provider = provider_factory(session)
        providers.append(provider)
        recorders[name] = Recorder(provider.get_tracer("agenttrace.proxy"), name)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.client = httpx.AsyncClient(timeout=None, transport=transport)  # one shared client
        yield
        await app.state.client.aclose()
        for provider in providers:
            provider.shutdown()  # send the last batch of spans

    app = FastAPI(title="AgentTrace HTTP proxy", lifespan=lifespan)

    def url_of(name: str) -> str:
        if name not in upstreams:
            raise HTTPException(404, f"unknown MCP server '{name}'")
        return upstreams[name]

    async def open_upstream(request: Request, method: str, url: str, **kwargs) -> httpx.Response:
        """Send the request upstream and keep the response open for streaming."""
        client: httpx.AsyncClient = request.app.state.client
        upstream_request = client.build_request(
            method, url, headers=pick_headers(request.headers, PASS_REQUEST), **kwargs)
        return await client.send(upstream_request, stream=True)

    async def relay_stream(upstream: httpx.Response, on_line=None, on_close=None):
        """Yield the upstream body line by line, letting `on_line` look at each line."""
        try:
            async for line in upstream.aiter_lines():
                if on_line:
                    on_line(line)
                yield line + "\n"
        finally:
            await upstream.aclose()
            if on_close:
                on_close()

    @app.post("/mcp/{name}")
    async def forward(name: str, request: Request):
        url, recorder = url_of(name), recorders[name]
        body = await request.json()
        messages = body if isinstance(body, list) else [body]  # JSON-RPC allows batches
        sent_ids = [m["id"] for m in messages if isinstance(m, dict) and "method" in m and "id" in m]
        for message in messages:
            if isinstance(message, dict):
                recorder.on_request(message)  # starts spans + adds the trace id to _meta (in place)
        upstream = await open_upstream(request, "POST", url, json=body)
        headers = pick_headers(upstream.headers, PASS_RESPONSE)

        if upstream.headers.get("content-type", "").startswith("text/event-stream"):
            def record_event(line: str) -> None:  # each SSE "data:" line is one JSON-RPC message
                if line.startswith("data:"):
                    try:
                        recorder.on_response(json.loads(line[5:]))
                    except json.JSONDecodeError:
                        pass  # keep-alive or non-JSON event: just relay it

            def close_unanswered() -> None:
                recorder.close_ids(sent_ids, "stream ended without a response")

            return StreamingResponse(relay_stream(upstream, record_event, close_unanswered),
                                     status_code=upstream.status_code, headers=headers,
                                     media_type="text/event-stream")

        raw = await upstream.aread()  # plain JSON (or an empty 202 for notifications)
        await upstream.aclose()
        if raw:
            try:
                data = json.loads(raw)
                for message in (data if isinstance(data, list) else [data]):
                    if isinstance(message, dict):
                        recorder.on_response(message)
            except json.JSONDecodeError:
                pass  # not JSON (e.g. an HTML error page): pass it on untouched
        recorder.close_ids(sent_ids, f"no JSON-RPC response (HTTP {upstream.status_code})")
        return Response(raw, status_code=upstream.status_code, headers=headers)

    @app.get("/mcp/{name}")
    async def listen(name: str, request: Request):
        """The optional server->client SSE stream: relayed untouched (server-started messages aren't recorded)."""
        upstream = await open_upstream(request, "GET", url_of(name))
        return StreamingResponse(relay_stream(upstream), status_code=upstream.status_code,
                                 headers=pick_headers(upstream.headers, PASS_RESPONSE))

    @app.delete("/mcp/{name}")
    async def end_session(name: str, request: Request):
        upstream = await open_upstream(request, "DELETE", url_of(name))
        body = await upstream.aread()
        await upstream.aclose()
        return Response(body, status_code=upstream.status_code,
                        headers=pick_headers(upstream.headers, PASS_RESPONSE))

    return app
