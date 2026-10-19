"""Two quick measurements: how fast does Obsergent store spans, and what does the proxy add to a call?

    python scripts/bench.py
Uses a temporary database and a throwaway server on a free port: your real data is not touched.
"""
import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from fastapi.testclient import TestClient
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from obsergent.server.app import create_app
from obsergent.storage.sqlite import SQLiteStorage

BOOKSHOP = Path(__file__).resolve().parent.parent / "examples" / "bookshop" / "bookshop_server.py"
CALLS = 200


def bench_ingest(tmp: Path, n_spans: int = 5000, batch: int = 500) -> None:
    mem = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "bench"}))
    provider.add_span_processor(SimpleSpanProcessor(mem))
    tracer = provider.get_tracer("bench")
    for i in range(n_spans // 5):  # 5 spans per trace
        with tracer.start_as_current_span("agent.run"):
            for step in range(4):
                with tracer.start_as_current_span("tools/call x") as s:
                    s.set_attribute("step", step)
                    s.set_attribute("mcp.method.name", "tools/call")
                    s.set_attribute("mcp.tool.arguments", json.dumps({"i": i}))
    spans = mem.get_finished_spans()
    bodies = [encode_spans(spans[i:i + batch]).SerializeToString() for i in range(0, len(spans), batch)]
    client = TestClient(create_app(SQLiteStorage(tmp / "bench.db")))
    start = time.perf_counter()
    for body in bodies:
        client.post("/v1/traces", content=body, headers={"content-type": "application/x-protobuf"})
    took = time.perf_counter() - start
    print(f"ingest:  {len(spans)} spans in {took:.2f} s  ->  {len(spans) / took:,.0f} spans/second")


def roundtrip_ms(cmd: list[str], env: dict) -> float:
    """Average time of one tools/call through `cmd` (a server, directly or behind the proxy)."""
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, env=env)

    def send(msg):
        p.stdin.write(json.dumps(msg) + "\n")
        p.stdin.flush()
        if "id" in msg:
            p.stdout.readline()

    send({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "bench", "version": "0"}}})
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    start = time.perf_counter()
    for i in range(1, CALLS + 1):
        send({"jsonrpc": "2.0", "id": i, "method": "tools/call",
              "params": {"name": "search_books", "arguments": {"query": "python"}}})
    took = (time.perf_counter() - start) / CALLS * 1000
    p.stdin.close()
    p.wait(timeout=20)
    return took


def bench_proxy(tmp: Path) -> None:
    storage = SQLiteStorage(tmp / "proxy.db")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(storage), host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.02)
    env = dict(os.environ, OBSERGENT_ENDPOINT=f"http://127.0.0.1:{port}")
    direct_cmd = [sys.executable, str(BOOKSHOP)]
    proxy_cmd = [sys.executable, "-m", "obsergent.cli", "proxy", "--name", "bench", "--", *direct_cmd]
    roundtrip_ms(direct_cmd, env)  # warm-up run: the first process start is always slower
    # Alternate direct/proxied runs and take the median, so noise affects both sides equally.
    runs = [(roundtrip_ms(direct_cmd, env), roundtrip_ms(proxy_cmd, env)) for repeat in range(5)]
    direct = statistics.median(direct for direct, proxied in runs)
    proxied = statistics.median(proxied for direct, proxied in runs)
    print(f"proxy:   {direct:.2f} ms per call directly, {proxied:.2f} ms through the proxy  "
          f"->  overhead {proxied - direct:.2f} ms per call  (median of 5 runs, {CALLS} calls each)")
    server.should_exit = True


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        bench_ingest(Path(d))
        bench_proxy(Path(d))
