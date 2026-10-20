"""Questions, agents and MCP servers, on four real questions recorded from the bookshop agent (agent_graph_run.json)."""
import time

import pytest
from fastapi.testclient import TestClient

from conftest import load_fixture_spans
from obsergent.analysis.agentgraph import build_graph
from obsergent.analysis.generations import find_generations
from obsergent.analysis.queries import build_thread, summarize_query, timeline
from obsergent.ingest.pipeline import ingest_spans
from obsergent.server import price_sync
from obsergent.server.app import create_app
from obsergent.storage.sqlite import SQLiteStorage

QUESTION = "Do you have a Python book in stock, and how much is it?"


@pytest.fixture
def store(tmp_path):
    storage = SQLiteStorage(tmp_path / "q.db")
    for source in ("models_dev", "litellm"):
        storage.save_prices(source, [price_sync.row("openai", "gpt-4o-mini", 0.15, 0.6, 0.075)], 1)
    ingest_spans(load_fixture_spans("agent_graph_run.json"), storage)
    return storage


@pytest.fixture
def client(store):
    return TestClient(create_app(store))


def by_trace(spans):
    runs = {}
    for span in spans:
        runs.setdefault(span.trace_id, []).append(span)
    return runs


# ------------------------------------------------------------------------------------ questions
def test_one_question_is_summarised_with_its_answer_models_and_tools():
    run = next(spans for spans in by_trace(load_fixture_spans("agent_graph_run.json")).values()
               if len(find_generations(spans)) == 3)
    generations = find_generations(run)
    summary = summarize_query(run[0].trace_id, run, generations)
    assert summary["question"] == QUESTION and summary["answer"].startswith("We have")
    assert summary["models"] == ["gpt-4o-mini"]  # the dated and undated names are one model
    assert summary["model_calls"] == 3 and summary["tool_calls"] == 3 and summary["status"] == "ok"
    assert summary["agent"] == "bookshop-agent" and summary["steps"] == 1 + 3 + 3
    assert summary["human_messages"] == 1 and summary["ai_messages"] == 6 and summary["exchanges"] == summary["steps"]
    expected = sum((g.prompt_tokens or 0) + (g.completion_tokens or 0) for g in generations)
    assert summary["tokens"]["total"] == expected > 0
    thread = build_thread(run, generations)
    assert [item["kind"] for item in thread][0] == "question" and thread[-1]["kind"] == "answer"
    tools = [item for item in thread if item["kind"] == "tool"]
    assert len(tools) == 3 and all(item["result"] for item in tools) and tools[0]["server"] in ("bookshop", "wso2")
    # the two sides add up to the steps, and every step has its tokens: exact for the model, estimated for the rest
    assert sum(item["side"] == "human" for item in thread) == 1 and sum(item["side"] == "ai" for item in thread) == 6
    models = [item for item in thread if item["kind"] in ("model", "answer")]
    assert [m["tokens"]["input"] for m in models] == [g.prompt_tokens for g in generations]
    assert all(m["tokens"]["exact"] for m in models) and not any(t["tokens"]["exact"] for t in tools)
    assert all(t["tokens"]["input"] == max(1, round(len(t["result"]) / 4)) for t in tools)
    assert thread[0]["tokens"] == {"input": round(len(QUESTION) / 4), "output": 0, "exact": False}


def test_the_questions_list_has_the_four_questions_and_not_the_gateway_traffic(store, client):
    ingest_spans(load_fixture_spans("apim_gateway.json"), store)  # gateway-only traffic: must NOT become a question
    cards = client.get("/api/queries").json()
    assert len(cards) == 4 and {c["question"] for c in cards} == {QUESTION}
    assert sorted(c["status"] for c in cards) == ["ok", "ok", "ok", "problem"]  # one run failed (the provider refused it)
    assert cards[0]["started_ns"] >= cards[-1]["started_ns"]  # newest first
    assert all(c["cost"]["enabled"] for c in cards)
    assert client.get("/api/queries", params={"q": "zzz-nothing"}).json() == []
    assert len(client.get("/api/queries", params={"limit": 2}).json()) == 2


def test_a_question_thread_over_the_api(client):
    card = next(c for c in client.get("/api/queries").json() if c["model_calls"] == 3)
    thread = client.get(f"/api/queries/{card['trace_id']}").json()
    assert thread["question"] == QUESTION and thread["thread"][0]["kind"] == "question"
    assert thread["cost"]["usd"] > 0 and "search_books" in thread["tools_offered"]
    assert any(item["kind"] == "model" and item["cost"] for item in thread["thread"])
    assert client.get(f"/api/queries/{card['trace_id'][:8]}").status_code == 200  # a short id works
    assert client.get("/api/queries/ffffffff").status_code == 404


def test_the_peaks_chart_has_one_point_per_question(client):
    points = client.get("/api/queries/timeline").json()
    assert points["mode"] == "questions" and len(points["points"]) == 4
    assert all(p["question"] == QUESTION and p["steps"] >= 1 and p["tokens"]["total"] >= 0 for p in points["points"])


def test_many_questions_are_grouped_into_time_slots():
    now = time.time_ns()
    cards = [{"trace_id": f"{i:032d}", "started_ns": now - i * 60 * 10**9, "question": f"q{i}",
              "steps": 3, "human_messages": 1, "ai_messages": 2,
              "tokens": {"input": 10, "output": 5, "cached": 0, "reasoning": 0, "total": 15},
              "model_calls": 1, "tool_calls": 1, "duration_ms": 5, "status": "ok", "cost": {"usd": 0.001}} for i in range(60)]
    grouped = timeline(cards, 24, now)
    assert grouped["mode"] == "slots" and sum(p["count"] for p in grouped["points"]) == 60
    assert sum(p["steps"] for p in grouped["points"]) == 180 and sum(p["tokens"]["total"] for p in grouped["points"]) == 900


def test_the_overview_counts_discussions_and_tools(client):
    overview = client.get("/api/stats/overview").json()
    assert overview["discussions"] == 4 and overview["tools_total"] == 2 and overview["mcps"] == 2
    assert len(overview["latest_queries"]) == 4 and overview["timeline"]["mode"] == "questions"
    assert [m["model"] for m in overview["models"]] == ["gpt-4o-mini"]


# ------------------------------------------------------------------------------------ agents
def test_the_agent_graph_follows_the_real_span_tree():
    graph = build_graph(by_trace(load_fixture_spans("agent_graph_run.json")))
    assert graph["framework"] == "LangGraph" and not graph["approximate"]
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert {"start", "end", "step:agent", "step:tools", "model:gpt-4o-mini", "tool:search_books",
            "tool:get_price_and_stock", "mcp:bookshop", "mcp:wso2", "gateway"} <= set(nodes)
    edges = {(e["source"], e["target"]): e for e in graph["edges"]}
    assert edges[("start", "step:agent")]["calls"] == 4  # four questions began with the agent step
    assert ("step:agent", "step:tools") in edges and ("step:tools", "step:agent") in edges  # the loop
    assert ("step:agent", "model:gpt-4o-mini") in edges and ("step:tools", "tool:search_books") in edges
    assert ("tool:search_books", "mcp:bookshop") in edges and edges[("step:agent", "end")]["calls"] >= 3
    assert nodes["model:gpt-4o-mini"]["calls"] == 10  # all ten model calls, the dated and undated name together
    assert nodes["model:gpt-4o-mini"]["tokens"] > 0 and nodes["tool:search_books"]["tokens"] == 0
    assert nodes["mcp:bookshop"]["calls"] == 3 and nodes["mcp:wso2"]["calls"] == 6  # one run direct, three via the gateway
    assert ("mcp:wso2", "gateway") in edges and ("mcp:bookshop", "gateway") not in edges


def test_an_agent_without_a_graph_is_chained_in_call_order_and_marked_approximate():
    spans = [s for s in load_fixture_spans("agent_graph_run.json") if s.name != "LangGraph"]
    graph = build_graph({"x": [s for s in spans if s.trace_id == spans[0].trace_id]})
    assert graph["approximate"] and graph["framework"] == "custom"
    assert {"start", "end"} <= {n["id"] for n in graph["nodes"]} and any(n["kind"] == "model" for n in graph["nodes"])


def test_the_agents_api(client):
    (agent,) = client.get("/api/agents").json()
    assert agent["name"] == "bookshop-agent" and agent["questions"] == 4 and agent["framework"] == "LangGraph"
    assert agent["models"] == ["gpt-4o-mini"] and set(agent["tools"]) == {"search_books", "get_price_and_stock"}
    assert agent["problems"] == 1 and agent["usd"] > 0 and "runs" not in agent
    graph = client.get("/api/agents/bookshop-agent/graph").json()
    assert graph["agent"] == "bookshop-agent" and any(n["kind"] == "model" and n["cost_usd"] > 0 for n in graph["nodes"])
    assert client.get("/api/agents/nobody/graph").status_code == 404


# ------------------------------------------------------------------------------------ MCP servers and models
def test_the_mcps_api_lists_servers_with_their_tools(store, client):
    newest = time.time_ns()  # the newest tool list of the server
    store.save_tool_snapshot("bookshop", [{"name": "search_books", "description": "Search",
                                           "inputSchema": {"type": "object", "required": ["query"],
                                                           "properties": {"query": {"type": "string"}}}},
                                          {"name": "delete_book", "description": "Remove", "inputSchema": {}}], newest)
    mcps = {m["name"]: m for m in client.get("/api/mcps").json()}
    mcp = mcps["bookshop"]
    assert mcps["wso2"]["via_gateway"] and not mcp["via_gateway"]
    assert mcp["name"] == "bookshop" and mcp["tool_count"] == 2 and mcp["calls"] >= 1
    tools = {t["name"]: t for t in mcp["tools"]}
    assert tools["search_books"]["parameters"] == [{"name": "query", "type": "string", "required": True,
                                                    "description": "", "choices": []}]
    assert tools["search_books"]["used"] and not tools["delete_book"]["used"] and tools["delete_book"]["risky"]


def test_the_models_api_carries_price_and_what_the_model_can_do(store, client):
    store.save_model_info([{"provider": "openai", "model": "gpt-4o-mini",
                            "info": {"name": "GPT-4o mini", "context": 128000, "tool_call": True}}])
    (model,) = client.get("/api/models").json()
    assert model["display"] == "GPT-4o mini" and model["info"]["context"] == 128000
    assert model["price"]["input"] == 0.15 and model["price"]["confidence"] == "confirmed"
    assert model["usd"] > 0 and model["questions"] == 4 and model["error_rate"] > 0 and model["versions"]


def test_models_dev_facts_are_stored_when_prices_are_downloaded(store):
    rows = price_sync.parse_models_dev_info({"openai": {"name": "OpenAI", "models": {"gpt-4o-mini": {
        "name": "GPT-4o mini", "limit": {"context": 128000, "output": 16384}, "tool_call": True, "open_weights": False,
        "modalities": {"input": ["text", "image"], "output": ["text"]}, "release_date": "2024-07-18"}}}})
    assert rows[0]["info"]["context"] == 128000 and rows[0]["info"]["input_modalities"] == ["text", "image"]
    store.save_model_info(rows)
    assert store.model_info(["gpt-4o-mini"])[0]["info"]["release_date"] == "2024-07-18"


@pytest.mark.parametrize("page", ["/api/queries", "/api/queries/timeline", "/api/agents", "/api/mcps", "/api/models",
                                  "/api/stats/overview"])
def test_the_new_pages_answer_on_an_empty_database(tmp_path, page):
    client = TestClient(create_app(SQLiteStorage(tmp_path / "empty.db")))
    assert client.get(page).status_code == 200


def test_the_schema_goes_from_version_6_to_7(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    SQLiteStorage(path)
    db = sqlite3.connect(path)
    db.execute("DROP TABLE model_info")
    db.execute("PRAGMA user_version = 6")
    db.commit()
    db.close()
    store = SQLiteStorage(path)
    store.save_model_info([{"provider": "p", "model": "m", "info": {"a": 1}}])
    assert store.model_info(["m"])[0]["info"] == {"a": 1}
