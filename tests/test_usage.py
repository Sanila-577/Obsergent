"""Token monitoring: totals, trends, where the tokens went, the daily budget and heavy questions."""
import time

import pytest
from fastapi.testclient import TestClient

from conftest import load_fixture_spans
from obsergent import config
from obsergent.analysis.usage import budget_status, change, heavy_questions, usage_report
from obsergent.cli import main
from obsergent.ingest.pipeline import ingest_spans
from obsergent.server import price_sync
from obsergent.server.app import create_app
from obsergent.storage.sqlite import SQLiteStorage

HOUR = 3600 * 10**9


@pytest.fixture
def store(tmp_path):
    storage = SQLiteStorage(tmp_path / "u.db")
    for source in ("models_dev", "litellm"):
        storage.save_prices(source, [price_sync.row("openai", "gpt-4o-mini", 0.15, 0.6, 0.075)], 1)
    ingest_spans(load_fixture_spans("agent_graph_run.json"), storage)
    return storage


@pytest.fixture
def client(store):
    return TestClient(create_app(store))


def recorded_tokens(spans) -> int:
    """The tokens written on the spans themselves (what every total must add up to)."""
    return sum(int(s.attributes.get("llm.token_count.prompt", 0)) + int(s.attributes.get("llm.token_count.completion", 0))
               for s in spans if s.attributes.get("openinference.span.kind") == "LLM")


def call(start, model="m", tokens_in=100, tokens_out=10, tools=(), trace="t"):
    return {"trace_id": trace, "span_id": f"{trace}{start}", "start_ns": start, "model": model, "provider": "p",
            "input": tokens_in, "output": tokens_out, "cached": 0, "reasoning": 0, "tool_definition": 20,
            "tools": list(tools), "usd": 0.01}


def test_the_report_adds_up_and_spreads_over_time():
    calls = [call(0, tools=["a", "b"]), call(5, model="n", tokens_in=1000), call(9, tokens_in=950, trace="u")]
    report = usage_report(calls, [], start=0, width=5, buckets=2, contexts={"m": 1000})
    assert report["totals"]["total"] == 110 + 1010 + 960 and report["totals"]["calls"] == 3
    assert [slot["total"] for slot in report["series"]] == [110, 1970]
    assert report["series"][1]["by_model"] == {"n": 1010, "m": 960}
    assert {m["model"]: m["total"] for m in report["by_model"]} == {"n": 1010, "m": 1070}
    assert report["by_tool"] == [{"tool": "a", "calls": 1, "total": 55}, {"tool": "b", "calls": 1, "total": 55}]
    assert report["tool_definitions"] == {"total": 60, "per_call": 20}
    assert [n["trace_id"] for n in report["near_limit"]] == ["u"]  # 950 of 1000 tokens: close to the model's limit


def test_the_budget_levels():
    assert budget_status(10, 0, 80) == {"enabled": False, "used": 10}
    assert budget_status(70, 100, 80)["level"] == "ok"
    assert budget_status(85, 100, 80)["level"] == "warn"
    assert budget_status(120, 100, 80)["level"] == "over"
    assert change(120, 100) == pytest.approx(0.2) and change(5, 0) is None


def test_heavy_questions_need_a_usual_or_an_alert():
    def q(i, total):
        return {"trace_id": str(i), "question": f"q{i}", "started_ns": i, "tokens": {"total": total}}

    usual = [q(i, 100) for i in range(5)]
    assert heavy_questions(usual + [q(9, 400)]) == []  # 4x the usual: not heavy yet
    assert [h["trace_id"] for h in heavy_questions(usual + [q(9, 5000)])] == ["9"]
    assert heavy_questions([q(1, 100), q(2, 3000)]) == []  # too few questions to know the usual
    assert [h["trace_id"] for h in heavy_questions([q(1, 100), q(2, 3000)], alert=1000)] == ["2"]


def test_the_usage_api_matches_the_recorded_tokens(client):
    expected = recorded_tokens(load_fixture_spans("agent_graph_run.json"))
    usage = client.get("/api/usage").json()
    assert usage["totals"]["total"] == expected and usage["totals"]["questions"] == 4
    assert sum(slot["total"] for slot in usage["series"]) == expected
    assert usage["by_model"][0]["model"] == "gpt-4o-mini" and usage["by_agent"][0]["agent"] == "bookshop-agent"
    assert usage["by_question"][0]["tokens"]["total"] >= usage["by_question"][-1]["tokens"]["total"]
    assert {t["tool"] for t in usage["by_tool"]} == {"search_books", "get_price_and_stock"}
    assert usage["budget"]["enabled"] is False
    overview = client.get("/api/stats/overview").json()
    assert overview["tokens"]["total"] == expected
    assert overview["steps_total"] == overview["human_messages"] + overview["ai_messages"]


def test_every_model_display_carries_its_tokens_and_a_trend(client):
    expected = recorded_tokens(load_fixture_spans("agent_graph_run.json"))
    (model,) = client.get("/api/models").json()
    assert model["tokens"]["total"] == expected
    assert sum(slot["input"] + slot["output"] for slot in model["series"]) == expected and len(model["series"]) == 24
    assert client.get("/api/spending").json()["by_model"][0]["prompt_tokens"] > 0
    (agent,) = client.get("/api/agents").json()
    assert agent["tokens"]["total"] == expected and agent["avg_tokens"] == expected / 4


def test_a_small_budget_warns_on_the_overview_and_in_things_to_check(client, monkeypatch):
    monkeypatch.setenv("OBSERGENT_TOKEN_BUDGET", "100")
    config.reload()
    try:
        overview = client.get("/api/stats/overview").json()
        assert overview["tokens"]["budget"]["level"] == "over"
        findings = client.get("/api/findings").json()
        assert any(f["type"] == "token_budget" and f["severity"] == "high" for f in findings)
    finally:
        monkeypatch.delenv("OBSERGENT_TOKEN_BUDGET")
        config.reload()


def test_the_usage_command_prints_totals(store, monkeypatch, capsys):
    monkeypatch.setattr(config, "db_path", lambda: store.path)
    assert main(["usage", "--hours", "24"]) == 0
    printed = capsys.readouterr().out
    assert "tokens" in printed and "gpt-4o-mini" in printed and "heaviest questions" in printed


def test_usage_on_an_empty_database(tmp_path):
    client = TestClient(create_app(SQLiteStorage(tmp_path / "empty.db")))
    usage = client.get("/api/usage").json()
    assert usage["totals"]["total"] == 0 and usage["by_model"] == [] and len(usage["series"]) == 24
    assert time.time_ns() > 0
