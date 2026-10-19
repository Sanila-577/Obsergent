"""End to end with a REAL model: the bookshop agent -> SDK + proxy -> live server -> API.

Runs only when Ollama is running with the model (default qwen2.5:7b, or OBSERGENT_TEST_MODEL), otherwise it is skipped.
It forces Ollama for the agent, so a paid provider chosen in .env is never called by the tests.
Nothing is scripted: the model decides which tools to call, so the checks are about what must be true of ANY run.
"""
import os
import subprocess
import sys
import time

import httpx
import pytest

from conftest import BOOKSHOP

AGENT_DIR = BOOKSHOP.parent
OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
# This test always uses a local Ollama model, whatever .env says (your .env may point at a paid service).
MODEL = os.environ.get("OBSERGENT_TEST_MODEL", "qwen2.5:7b")


def ollama_has_model() -> bool:
    try:
        names = [m["name"] for m in httpx.get(f"{OLLAMA}/api/tags", timeout=2).json()["models"]]
    except (httpx.HTTPError, KeyError, ValueError):
        return False
    return MODEL in names


def run_agent(endpoint: str, question: str = "Do you have a Python book in stock, and how much is it?") -> str:
    env = dict(os.environ, OBSERGENT_ENDPOINT=endpoint, LLM_PROVIDER="ollama", LLM_MODEL=MODEL)
    for name in ("MCP_PROXY_TRACEPARENT", "TRACEPARENT"):
        env.pop(name, None)
    done = subprocess.run([sys.executable, "agent.py", question], cwd=AGENT_DIR, env=env, capture_output=True,
                          text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    return done.stdout.strip()


def wait_for_run(url: str, attempts: int = 60) -> dict:
    """The agent and the proxy export their spans in the background: wait until the run has its MCP calls."""
    for attempt in range(attempts):
        runs = [t for t in httpx.get(f"{url}/api/traces").json() if t["root_name"] == "agent.run"]
        if runs and runs[0]["tool_calls"] >= 1 and runs[0]["llm_calls"] >= 2:
            return runs[0]
        time.sleep(0.25 * (1 + attempt // 10))
    raise AssertionError("the run never appeared in the API")


@pytest.mark.skipif(not ollama_has_model(), reason="needs Ollama running with the model (default qwen2.5:7b)")
def test_real_agent_run_is_recorded_end_to_end(live_server):
    url, _ = live_server
    assert run_agent(url)

    run = wait_for_run(url)
    assert run["chat_session"] == "bookshop-demo" and run["user_id"] == "demo-user"  # set by at.context(...)
    assert MODEL in run["models"] and run["total_tokens"] > 0

    conversation = httpx.get(f"{url}/api/traces/{run['trace_id']}/conversation").json()
    assert conversation["messages"][0]["role"] == "system" and conversation["messages"][-1]["role"] == "assistant"
    asked = next(call for m in conversation["messages"] for call in m["tool_calls"])
    assert asked["link"]["mcp_span_id"]  # the model's request is linked to the real MCP call
    detail = httpx.get(f"{url}/api/traces/{run['trace_id']}").json()
    mcp = next(s for s in detail["spans"] if s["span_id"] == asked["link"]["mcp_span_id"])
    assert mcp["service"] == "obsergent-proxy" and mcp["attributes"]["gen_ai.tool.name"] == asked["name"]
