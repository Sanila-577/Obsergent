"""Shared test helpers: a live AgentTrace server, and a way to drive the stdio proxy like a real client."""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans

from agenttrace.server.app import create_app
from agenttrace.storage.sqlite import SQLiteStorage

ROOT = Path(__file__).resolve().parent.parent
BOOKSHOP = ROOT / "examples" / "bookshop" / "bookshop_server.py"

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "pytest", "version": "0"}}}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}  # a notification: no id, no answer


def call_msg(msg_id, name, arguments):
    return {"jsonrpc": "2.0", "id": msg_id, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


def post_spans(client, spans):
    """Send OpenTelemetry spans to an AgentTrace app the way a real exporter does (OTLP/protobuf)."""
    return client.post("/v1/traces", content=encode_spans(spans).SerializeToString(),
                       headers={"content-type": "application/x-protobuf"})


@pytest.fixture
def live_server(tmp_path):
    """A real AgentTrace server on a free port with a temporary database. Yields (url, storage)."""
    storage = SQLiteStorage(tmp_path / "live.db")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(storage), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}", storage
    server.should_exit = True
    thread.join(timeout=5)


def run_proxy(endpoint: str, server_cmd: list[str], messages: list[dict], name="bookshop", env_extra=None):
    """Start `agenttrace proxy`, send the messages like an MCP client, return the replies by id."""
    env = dict(os.environ, AGENTTRACE_ENDPOINT=endpoint, **(env_extra or {}))
    env.pop("MCP_PROXY_TRACEPARENT", None)  # a closed app sends none
    proc = subprocess.Popen([sys.executable, "-m", "agenttrace.cli", "proxy", "--name", name, "--", *server_cmd],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    replies, expected = {}, [m["id"] for m in messages if "id" in m]
    for m in messages:
        proc.stdin.write(json.dumps(m) + "\n")
        proc.stdin.flush()
        if "id" in m:  # wait for each answer so requests stay in order (a real client does too)
            line = proc.stdout.readline()
            reply = json.loads(line)
            replies[reply["id"]] = reply
    assert set(replies) == set(expected)
    proc.stdin.close()  # the client hangs up -> the proxy flushes its spans and exits
    proc.wait(timeout=20)
    return replies


@pytest.fixture
def bookshop_cmd():
    return [sys.executable, str(BOOKSHOP)]
