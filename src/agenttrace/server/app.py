"""The AgentTrace server: receives OTLP spans and serves the REST API.

    SDK / proxy ──POST /v1/traces──► parse (ingest/otlp.py) ──► save (storage) ──► SQLite
    you / CLI   ──GET  /api/...  ──► read (storage) + analysis (smells, drift)

Run with `agenttrace up` (cli.py). The web UI will be added later and served from
server/static/.
"""
import gzip
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Request, Response
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse

from agenttrace import config
from agenttrace.analysis.safety import drift_report
from agenttrace.analysis.smells import find_smells
from agenttrace.ingest.otlp import parse_export_json, parse_export_request
from agenttrace.ingest.pipeline import ingest_spans
from agenttrace.storage.sqlite import SQLiteStorage


def create_app(storage: SQLiteStorage | None = None) -> FastAPI:
    # One object plays both roles (spans + metadata). Tests pass in a temporary database.
    store = storage or SQLiteStorage(config.DB_PATH)
    app = FastAPI(title="AgentTrace", version="0.1.0")

    # ----------------------------------------------------------------- ingest
    @app.post("/v1/traces")
    async def receive_otlp(request: Request) -> Response:
        """Standard OTLP/HTTP endpoint - point any OpenTelemetry exporter here.

        Accepts protobuf (what the Python exporters send) and JSON (what some
        collectors and curl-based tools send).
        """
        content_type = request.headers.get("content-type", "")
        body = await request.body()
        if request.headers.get("content-encoding") == "gzip":  # exporters may compress
            body = gzip.decompress(body)
        try:
            if "protobuf" in content_type:
                spans = parse_export_request(body)
            elif "json" in content_type:
                spans = parse_export_json(body)
            else:
                raise HTTPException(415, "Send OTLP as application/x-protobuf or application/json")
        except (DecodeError, ValueError) as err:  # bad bytes / bad JSON / bad hex ids
            raise HTTPException(400, f"Could not parse the OTLP request: {err}") from err
        ingest_spans(spans, store, store)
        # The reply uses the same format as the request (an empty "success" message).
        if "json" in content_type:
            return Response("{}", media_type="application/json")
        return Response(ExportTraceServiceResponse().SerializeToString(), media_type="application/x-protobuf")

    # -------------------------------------------------------------------- API
    @app.get("/api/traces")
    def list_traces(limit: int = 50, service: str | None = None, session_id: str | None = None):
        return store.list_traces(limit=limit, service=service, session_id=session_id)

    @app.get("/api/traces/{trace_id}")
    def get_trace(trace_id: str):
        # Accept a short prefix, like the CLI prints.
        full_id = store.resolve_trace_id(trace_id) or trace_id
        spans = store.get_trace(full_id)
        if not spans:
            raise HTTPException(404, "trace not found")
        return {"trace_id": full_id,
                "spans": [asdict(s) | {"duration_ms": s.duration_ms} for s in spans],
                "smells": find_smells(spans)}

    @app.get("/api/sessions")
    def list_sessions(limit: int = 50):
        return store.list_sessions(limit=limit)

    @app.get("/api/sessions/{session_id}/traces")
    def session_traces(session_id: str, limit: int = 200):
        return store.list_traces(limit=limit, session_id=session_id)

    @app.get("/api/servers")
    def list_servers():
        return store.list_servers()

    @app.get("/api/servers/{name}/snapshots")
    def server_snapshots(name: str):
        snapshots = store.list_tool_snapshots(name)
        if not snapshots:
            raise HTTPException(404, "no tool snapshots for that server")
        return {"server": name, "snapshots": snapshots, "drift": drift_report(snapshots)}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
