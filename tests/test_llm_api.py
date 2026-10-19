"""The model-call API: generations, conversation, per-model usage and the runs-list columns."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from obsergent.analysis.generations import find_generations
from obsergent.models import Span
from obsergent.server.app import create_app
from obsergent.storage.sqlite import SQLiteStorage

FIXTURE = Path(__file__).parent / "fixtures" / "ollama_run.json"


@pytest.fixture
def client(tmp_path):
    storage = SQLiteStorage(tmp_path / "t.db")
    storage.save_spans([Span(**row) for row in json.loads(FIXTURE.read_text())])
    return TestClient(create_app(storage))


def test_generations_endpoint(client):
    trace_id = client.get("/api/traces").json()[0]["trace_id"]
    body = client.get(f"/api/traces/{trace_id[:8]}/generations").json()  # an id prefix is enough
    assert body["trace_id"] == trace_id
    assert body["summary"]["calls"] == 3 and body["summary"]["models"] == ["qwen2.5:7b"]
    first = body["generations"][0]
    assert first["model"] == "qwen2.5:7b" and first["total_tokens"] == 263 and first["latency_ms"] > 0
    assert first["tool_links"][0]["name"] == "search_books" and first["tool_links"][0]["mcp_span_id"]


def test_conversation_endpoint(client):
    trace_id = client.get("/api/traces").json()[0]["trace_id"]
    body = client.get(f"/api/traces/{trace_id}/conversation").json()
    assert [m["role"] for m in body["messages"]][:3] == ["system", "user", "assistant"]
    assert body["messages"][-1]["role"] == "assistant" and "39.99" in body["messages"][-1]["content"]


def test_unknown_trace_is_404(client):
    assert client.get("/api/traces/ffffffff/generations").status_code == 404
    assert client.get("/api/traces/ffffffff/conversation").status_code == 404


def test_models_endpoint(client):
    (usage,) = client.get("/api/models").json()
    assert usage["model"] == "qwen2.5:7b" and usage["provider"] == "ollama" and usage["calls"] == 3
    expected = sum(g.total_tokens for g in find_generations([Span(**row) for row in json.loads(FIXTURE.read_text())]))
    assert usage["total_tokens"] == expected  # summed over the three calls
    assert usage["p95_ms"] >= usage["avg_ms"] > 0 and usage["max_ms"] >= usage["p95_ms"]


def test_runs_list_shows_models_tokens_and_filters_by_model(client):
    (run,) = client.get("/api/traces").json()
    assert run["models"] == "qwen2.5:7b" and run["llm_calls"] == 3 and run["total_tokens"] > 0
    assert len(client.get("/api/traces", params={"model": "qwen"}).json()) == 1
    assert client.get("/api/traces", params={"model": "gpt"}).json() == []
