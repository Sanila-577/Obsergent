"""Cost in the API: runs, model calls, models, the Spending page and the price status (prices come from the database)."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from agenttrace.ingest.pipeline import ingest_spans
from agenttrace.models import Span
from agenttrace.server import costing, price_sync
from agenttrace.server.app import create_app
from agenttrace.storage.sqlite import SQLiteStorage
from conftest import load_fixture_spans

HOUR = 3_600 * 1_000_000_000


def llm_span(trace, name, provider, model, prompt, completion, start_ns, question="How much is Fluent Python?", **extra):
    """A model-call span shaped like the OpenInference LangChain instrumentor writes it."""
    attributes = {"openinference.span.kind": "LLM", "llm.model_name": model, "llm.provider": provider,
                  "llm.token_count.prompt": prompt, "llm.token_count.completion": completion,
                  "llm.token_count.total": prompt + completion,
                  "llm.input_messages.0.message.role": "user", "llm.input_messages.0.message.content": question} | extra
    return Span(trace, f"{trace}-{name}", None, name, "INTERNAL", "agent", start_ns, start_ns + 1_000_000, attributes=attributes)


@pytest.fixture
def store(tmp_path):
    storage = SQLiteStorage(tmp_path / "cost.db")
    # What price_sync would have stored: gpt-4o-mini at $0.15 in / $0.60 out (models.dev and LiteLLM agree).
    for source in ("models_dev", "litellm"):
        storage.save_prices(source, [price_sync.row("openai", "gpt-4o-mini", 0.15, 0.6, 0.075)], 1)
    return storage


@pytest.fixture
def client(store):
    return TestClient(create_app(store))


def add_run(store, trace, model="gpt-4o-mini", provider="openai", prompt=1000, completion=100, start_ns=None, **extra):
    started = start_ns or time.time_ns() - HOUR // 2
    ingest_spans([llm_span(trace, "chat", provider, model, prompt, completion, started, **extra)], store)


def test_a_run_has_a_cost_and_the_question_as_its_title(store, client):
    add_run(store, "a" * 32)
    run = client.get("/api/traces").json()[0]
    assert run["cost"]["usd"] == pytest.approx(1000 * 0.15e-6 + 100 * 0.6e-6) and run["cost"]["priced"] == 1
    assert run["question"] == "How much is Fluent Python?"
    assert client.get(f"/api/traces/{'a' * 32}").json()["cost"]["usd"] == pytest.approx(0.00021)


def test_every_model_call_carries_its_cost_and_the_summary_the_total(store, client):
    add_run(store, "b" * 32)
    body = client.get(f"/api/traces/{'b' * 32}/generations").json()
    call = body["generations"][0]["cost"]
    assert call["status"] == "priced" and call["confidence"] == "confirmed" and call["source"] == "models_dev"
    assert body["summary"]["cost"]["usd"] == pytest.approx(call["usd"])


def test_cached_tokens_are_priced_with_the_cache_price(store, client):
    add_run(store, "c" * 32, prompt=2000, completion=0, **{"llm.token_count.prompt_details.cache_read": 1000})
    call = client.get(f"/api/traces/{'c' * 32}/generations").json()["generations"][0]["cost"]
    assert call["usd"] == pytest.approx(1000 * 0.15e-6 + 1000 * 0.075e-6)


def test_a_local_model_costs_nothing_and_an_unknown_one_is_unpriced(store, client, monkeypatch):
    requested = []
    monkeypatch.setattr(price_sync, "request_refresh", lambda storage, *args: requested.append(1))
    add_run(store, "d" * 32, model="qwen2.5:7b", provider="ollama")
    add_run(store, "e" * 32, model="mystery-1", provider="acme")
    runs = {run["trace_id"]: run["cost"] for run in client.get("/api/traces").json()}
    assert runs["d" * 32]["local"] == 1 and runs["d" * 32]["usd"] == 0
    assert runs["e" * 32]["unpriced"] == 1 and runs["e" * 32]["usd"] == 0
    assert requested  # an unknown model asks for a (rate-limited) refresh of the price lists


def test_the_spending_page_data(store, client):
    add_run(store, "f" * 32, prompt=1_000_000, completion=0)  # $0.15
    add_run(store, "0" * 32, model="qwen2.5:7b", provider="ollama")
    data = client.get("/api/spending?hours=24&buckets=4").json()
    assert data["totals"]["usd"] == pytest.approx(0.15) and data["totals"]["local"] == 1
    assert [m["model"] for m in data["by_model"]][0] == "gpt-4o-mini"
    assert sum(bucket["usd"] for bucket in data["series"]) == pytest.approx(0.15) and len(data["series"]) == 4
    assert data["top_runs"][0]["trace_id"] == "f" * 32 and data["top_runs"][0]["question"].startswith("How much")


def test_models_list_carries_cost(store, client):
    add_run(store, "1" * 32, prompt=1_000_000, completion=0)
    entry = next(m for m in client.get("/api/models").json() if m["model"] == "gpt-4o-mini")
    assert entry["cost_usd"] == pytest.approx(0.15)


def test_overview_has_a_cost_summary(store, client):
    add_run(store, "2" * 32, prompt=1_000_000, completion=0)
    assert client.get("/api/stats/overview").json()["cost"]["totals"]["usd"] == pytest.approx(0.15)


def test_a_price_change_uses_the_price_valid_at_the_time_unless_repriced_at_now(store, client):
    call_time = time.time_ns() - 2 * HOUR
    # The price went up an hour ago, after the call was made.
    store.save_prices("models_dev", [price_sync.row("openai", "gpt-4o-mini", 0.30, 0.6, 0.075)], time.time_ns() - HOUR)
    add_run(store, "3" * 32, prompt=1_000_000, completion=0, start_ns=call_time)
    then = client.get(f"/api/traces/{'3' * 32}/generations").json()["generations"][0]["cost"]["usd"]
    now = client.get(f"/api/traces/{'3' * 32}/generations?reprice=now").json()["generations"][0]["cost"]["usd"]
    assert then == pytest.approx(0.15) and now == pytest.approx(0.30)


def test_prices_status_and_refresh_on_an_empty_database(tmp_path, monkeypatch):
    fresh = TestClient(create_app(SQLiteStorage(tmp_path / "empty.db")))
    status = fresh.get("/api/prices").json()
    assert status["sources"] == [] and status["last_checked_ns"] == 0
    monkeypatch.setattr(price_sync, "refresh", lambda storage, force=False, client=None: {"models_dev": "3 models"})
    assert fresh.post("/api/prices/refresh").json()["outcome"] == {"models_dev": "3 models"}
    assert fresh.get("/api/spending").json()["totals"]["calls"] == 0


def test_pricing_can_be_switched_off(store, client, monkeypatch):
    add_run(store, "4" * 32)
    monkeypatch.setenv("AGENTTRACE_PRICING", "false")
    assert client.get("/api/spending").json() == {"enabled": False}
    assert client.get("/api/traces").json()[0]["cost"] == {"enabled": False}


def test_the_real_ollama_run_is_local_and_free(tmp_path):
    storage = SQLiteStorage(tmp_path / "o.db")
    ingest_spans(load_fixture_spans("ollama_run.json"), storage)
    run = TestClient(create_app(storage)).get("/api/traces").json()[0]
    assert run["cost"]["local"] == 3 and run["cost"]["usd"] == 0
    assert costing.first_question([]) == ""


def openrouter_output(cost: float) -> str:
    """output.value of a LangChain model call that went through OpenRouter (usage carries the provider's own charge)."""
    usage = {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100, "cost": cost, "is_byok": False,
             "cost_details": {"upstream_inference_cost": None}}
    return json.dumps({"generations": [[{"message": {"kwargs": {"response_metadata": {}}}}]],
                       "llm_output": {"token_usage": usage, "service_tier": None}})


def test_the_providers_own_cost_is_used_and_counted_as_exact(store, client):
    add_run(store, "5" * 32, **{"output.value": openrouter_output(0.5)})   # estimate would be $0.00021
    add_run(store, "6" * 32)                                              # an ordinary estimated run
    runs = {run["trace_id"]: run["cost"] for run in client.get("/api/traces").json()}
    assert runs["5" * 32]["usd"] == pytest.approx(0.5) and runs["5" * 32]["exact"] == 1
    call = client.get(f"/api/traces/{'5' * 32}/generations").json()["generations"][0]["cost"]
    assert call["confidence"] == "exact" and call["source"] == "openrouter" and call["breakdown"][0]["usd"] == 0.5
    totals = client.get("/api/spending").json()["totals"]
    assert totals["exact_usd"] == pytest.approx(0.5) and totals["estimated_usd"] == pytest.approx(0.00021)


def test_exact_cost_can_be_switched_off_to_see_the_estimate(store, client, monkeypatch):
    monkeypatch.setenv("AGENTTRACE_PRICING_EXACT", "false")
    add_run(store, "7" * 32, **{"output.value": openrouter_output(0.5)})
    assert client.get(f"/api/traces/{'7' * 32}").json()["cost"]["usd"] == pytest.approx(0.00021)


def test_price_changes_are_listed_for_the_notice(store, client):
    store.save_prices("models_dev", [price_sync.row("openai", "gpt-4o-mini", 0.20, 0.6, 0.075)], time.time_ns())
    changes = client.get("/api/prices").json()["changes"]
    assert changes and changes[0]["model"] == "gpt-4o-mini" and (changes[0]["old_input"], changes[0]["new_input"]) == (0.15, 0.20)
    assert client.get("/api/prices").json()["refresh_minutes"]["openrouter"] == 30


def test_only_real_price_changes_are_listed_not_other_updates_to_a_row(store, client):
    # Same input and output, but a new service-tier price appeared: the row changes, the price did not.
    store.save_prices("models_dev", [price_sync.row("openai", "gpt-4o-mini", 0.15, 0.6, 0.075,
                                                    extra={"service_tiers": {"batch": {"input": 0.075}}})], time.time_ns())
    assert client.get("/api/prices").json()["changes"] == []
