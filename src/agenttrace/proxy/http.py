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
        for p in providers:
            p.shutdown()  # send the last batch of spans

    app = FastAPI(title="AgentTrace HTTP proxy", lifespan=lifespan)

    def upstream_of(name: str) -> tuple[str, Recorder]:
        if name not in upstreams:
            raise HTTPException(404, f"unknown MCP server '{name}'")
        return upstreams[name], recorders[name]

    def forward_headers(request: Request) -> dict:
        return {k: v for k, v in request.headers.items() if k.lower() in PASS_REQUEST}

    def reply_headers(upstream: httpx.Response) -> dict:
        return {k: v for k, v in upstream.headers.items() if k.lower() in PASS_RESPONSE}

    @app.post("/mcp/{name}")
    async def forward(name: str, request: Request):
        url, recorder = upstream_of(name)
        body = await request.json()
        messages = body if isinstance(body, list) else [body]  # JSON-RPC allows batches
        sent_ids = [m["id"] for m in messages if isinstance(m, dict) and "method" in m and "id" in m]
        for m in messages:
            if isinstance(m, dict):
                recorder.on_request(m)  # starts spans + adds the trace id to _meta (in place)
        client: httpx.AsyncClient = request.app.state.client
        upstream = await client.send(
            client.build_request("POST", url, json=body, headers=forward_headers(request)), stream=True)

        if upstream.headers.get("content-type", "").startswith("text/event-stream"):
            async def relay():  # SSE: pass every line through, record each "data:" line
                try:
                    async for line in upstream.aiter_lines():
                        if line.startswith("data:"):
                            try:
                                recorder.on_response(json.loads(line[5:]))
                            except json.JSONDecodeError:
                                pass  # keep-alive or non-JSON event: just relay it
                        yield line + "\n"
                finally:
                    await upstream.aclose()
                    recorder.close_ids(sent_ids, "stream ended without a response")
            return StreamingResponse(relay(), status_code=upstream.status_code, headers=reply_headers(upstream),
                                     media_type="text/event-stream")

        raw = await upstream.aread()  # plain JSON (or an empty 202 for notifications)
        await upstream.aclose()
        if raw:
            try:
                data = json.loads(raw)
                for m in (data if isinstance(data, list) else [data]):
                    if isinstance(m, dict):
                        recorder.on_response(m)
            except json.JSONDecodeError:
                pass  # not JSON (e.g. an HTML error page): pass it on untouched
        recorder.close_ids(sent_ids, f"no JSON-RPC response (HTTP {upstream.status_code})")
        return Response(raw, status_code=upstream.status_code, headers=reply_headers(upstream))

    @app.get("/mcp/{name}")
    async def listen(name: str, request: Request):
        """The optional server->client SSE stream: relayed untouched (server-started messages aren't recorded)."""
        url, _ = upstream_of(name)
        client: httpx.AsyncClient = request.app.state.client
        upstream = await client.send(client.build_request("GET", url, headers=forward_headers(request)), stream=True)

        async def relay():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()
        return StreamingResponse(relay(), status_code=upstream.status_code, headers=reply_headers(upstream))

    @app.delete("/mcp/{name}")
    async def end_session(name: str, request: Request):
        url, _ = upstream_of(name)
        upstream = await request.app.state.client.delete(url, headers=forward_headers(request))
        return Response(upstream.content, status_code=upstream.status_code, headers=reply_headers(upstream))

    return app
