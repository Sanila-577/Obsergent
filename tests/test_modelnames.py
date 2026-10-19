"""One name per model: the dated and the undated name of a model are the same model."""
import json
import time

from fastapi.testclient import TestClient

from conftest import ROOT
from obsergent.analysis.modelnames import canonical, display, group_key
from obsergent.ingest.pipeline import ingest_spans
from obsergent.models import Span
from obsergent.server.app import create_app
from obsergent.storage.sqlite import SQLiteStorage

VECTORS = json.loads((ROOT / "tests" / "fixtures" / "model_names.json").read_text())


def test_every_shared_example_gets_its_display_name():
    for case in VECTORS:  # ui/src/lib/models.test.ts runs the same list
        assert display(case["name"]) == case["display"], case


def test_the_dated_and_the_undated_name_are_one_group():
    assert group_key("gpt-4o-mini", "openai") == group_key("gpt-4o-mini-2024-07-18", "OpenAI")
    assert canonical(None) == "unknown model"
    assert group_key("gpt-4o-mini", "openai") != group_key("gpt-4o-mini", "azure")


def llm(trace, span_id, model, start):
    attributes = {"openinference.span.kind": "LLM", "llm.model_name": model, "llm.provider": "openai",
                  "llm.token_count.prompt": 10, "llm.token_count.completion": 5, "llm.token_count.total": 15,
                  "llm.input_messages.0.message.role": "user", "llm.input_messages.0.message.content": "hi"}
    return Span(trace, span_id, None, "ChatOpenAI", "INTERNAL", "agent", start, start + 1_000_000, attributes=attributes)


def test_the_two_names_of_your_real_data_become_one_model_everywhere(tmp_path):
    store = SQLiteStorage(tmp_path / "m.db")
    now = time.time_ns()
    ingest_spans([llm("a" * 32, "1" * 16, "gpt-4o-mini", now - 5_000_000_000),
                  llm("b" * 32, "2" * 16, "gpt-4o-mini-2024-07-18", now - 4_000_000_000),
                  llm("b" * 32, "3" * 16, "gpt-4o-mini-2024-07-18", now - 3_000_000_000)], store)
    client = TestClient(create_app(store))
    (usage,) = store.list_model_usage()
    assert usage["model"] == "gpt-4o-mini" and usage["calls"] == 3
    assert usage["versions"] == ["gpt-4o-mini", "gpt-4o-mini-2024-07-18"]
    (model,) = client.get("/api/models").json()
    assert model["model"] == "gpt-4o-mini" and model["calls"] == 3 and model["questions"] == 2
    assert model["versions"] == ["gpt-4o-mini", "gpt-4o-mini-2024-07-18"] and model["prompt_tokens"] == 30
    overview = client.get("/api/stats/overview").json()
    assert [m["model"] for m in overview["models"]] == ["gpt-4o-mini"]
    spending = client.get("/api/spending").json()
    assert spending["enabled"] and [m["model"] for m in spending["by_model"]] == ["gpt-4o-mini"]
