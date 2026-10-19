"""Model calls inside the agent, rebuilt from the flat span attributes.

The main fixture is a REAL run: the bookshop agent with Ollama (qwen2.5:7b) answering
"Do you have a Python book in stock, and how much is it?" through the Obsergent proxy.
"""
import json
from pathlib import Path

import pytest

from obsergent.analysis.generations import (
    build_conversation,
    find_generations,
    parse_messages,
    summarize_generations,
)
from obsergent.models import Span

FIXTURE = Path(__file__).parent / "fixtures" / "ollama_run.json"


def load_spans(path: Path = FIXTURE) -> list[Span]:
    return [Span(**row) for row in json.loads(path.read_text())]


@pytest.fixture
def run():
    return find_generations(load_spans())


def test_real_run_has_three_model_calls_with_model_and_tokens(run):
    assert len(run) == 3
    first, last = run[0], run[2]
    assert first.model == "qwen2.5:7b" and first.provider == "ollama"
    assert (first.prompt_tokens, first.completion_tokens, first.total_tokens) == (243, 20, 263)
    assert last.total_tokens == 421 and last.latency_ms > 0
    assert first.tools == ["search_books", "get_price_and_stock"]  # the tools offered to the model
    assert "tools" not in first.parameters  # the bulky tool list is not duplicated in the parameters


def test_messages_are_rebuilt_in_order(run):
    first_input = run[0].input_messages
    assert [m.role for m in first_input] == ["system", "user"]
    assert "bookshop assistant" in first_input[0].content
    request = run[0].output_messages[0]
    assert request.role == "assistant" and request.content == ""
    assert request.tool_calls[0]["name"] == "search_books"
    assert json.loads(request.tool_calls[0]["arguments"]) == {"query": "Python"}
    # the last call saw the whole history, including both tool results (stored as content parts)
    roles = [m.role for m in run[2].input_messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "tool"]
    tool_message = run[2].input_messages[3]
    assert tool_message.name == "search_books" and "Python Crash Course" in tool_message.content
    assert tool_message.tool_call_id == run[0].output_messages[0].tool_calls[0]["id"]


def test_model_tool_calls_are_linked_to_the_real_mcp_calls(run):
    spans = {s.span_id: s for s in load_spans()}
    for generation, expected_tool in ((run[0], "search_books"), (run[1], "get_price_and_stock")):
        (link,) = generation.tool_links
        assert link.name == expected_tool
        assert spans[link.tool_span_id].attributes["tool.name"] == expected_tool  # the agent's TOOL span
        mcp = spans[link.mcp_span_id]
        assert mcp.attributes["mcp.method.name"] == "tools/call"  # the proxy's span...
        assert mcp.parent_span_id == link.tool_span_id  # ...is the child of that TOOL span
        assert link.mcp_status == "UNSET"
    assert run[2].tool_links == []  # the final answer asks for no tool


def test_conversation_is_the_whole_chat_with_links(run):
    conversation = build_conversation(run)
    roles = [m["role"] for m in conversation]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "tool", "assistant"]
    assert "costs $39.99" in conversation[-1]["content"]  # the final answer
    asked = conversation[2]["tool_calls"][0]
    assert asked["name"] == "search_books" and asked["link"]["mcp_span_id"]
    # the tool result points at the same MCP call
    assert conversation[3]["link"]["mcp_span_id"] == asked["link"]["mcp_span_id"]


def test_summary_totals(run):
    summary = summarize_generations(run)
    assert summary["calls"] == 3 and summary["models"] == ["qwen2.5:7b"]
    assert summary["total_tokens"] == sum(g.total_tokens for g in run)
    assert summary["prompt_tokens"] + summary["completion_tokens"] == summary["total_tokens"]
    assert summary["latency_ms"] == pytest.approx(sum(g.latency_ms for g in run))


def make_span(span_id, name, start, end, **attributes):
    return Span("t" * 32, span_id, None, name, "INTERNAL", "agent", start, end, attributes=attributes)


def test_opentelemetry_genai_names_are_understood():
    span = make_span("a1", "chat gpt", 1, 2, **{"gen_ai.request.model": "gpt-x", "gen_ai.system": "openai",
                                                "gen_ai.usage.input_tokens": 10, "gen_ai.usage.output_tokens": 5})
    (generation,) = find_generations([span])
    assert (generation.model, generation.provider) == ("gpt-x", "openai")
    assert (generation.prompt_tokens, generation.completion_tokens, generation.total_tokens) == (10, 5, 15)


def test_mcp_spans_and_plain_spans_are_not_generations():
    spans = [make_span("a1", "tools/call x", 1, 2, **{"mcp.method.name": "tools/call", "llm.model_name": "m"}),
             make_span("a2", "agent.run", 1, 2)]
    assert find_generations(spans) == []
    assert build_conversation([]) == [] and summarize_generations([])["total_tokens"] is None


def test_repeated_calls_of_the_same_tool_are_matched_in_order():
    def llm(span_id, start, end, call_id):
        return make_span(span_id, "chat", start, end, **{
            "openinference.span.kind": "LLM", "llm.model_name": "m",
            "llm.output_messages.0.message.role": "assistant",
            "llm.output_messages.0.message.tool_calls.0.tool_call.id": call_id,
            "llm.output_messages.0.message.tool_calls.0.tool_call.function.name": "search",
            "llm.output_messages.0.message.tool_calls.0.tool_call.function.arguments": "{}"})

    def tool(span_id, start, end):
        return make_span(span_id, "search", start, end, **{"openinference.span.kind": "TOOL", "tool.name": "search"})

    spans = [llm("l1", 0, 10, "c1"), tool("t1", 11, 20), llm("l2", 21, 30, "c2"), tool("t2", 31, 40)]
    first, second = find_generations(spans)
    assert first.tool_links[0].tool_span_id == "t1" and second.tool_links[0].tool_span_id == "t2"


def test_tool_call_without_a_matching_tool_span_stays_unlinked():
    span = make_span("l1", "chat", 0, 10, **{
        "openinference.span.kind": "LLM", "llm.output_messages.0.message.role": "assistant",
        "llm.output_messages.0.message.tool_calls.0.tool_call.id": "c1",
        "llm.output_messages.0.message.tool_calls.0.tool_call.function.name": "ghost"})
    (generation,) = find_generations([span])
    assert generation.tool_links[0].tool_span_id is None and generation.tool_links[0].mcp_span_id is None


def test_message_parts_are_joined_and_broken_keys_ignored():
    attributes = {"llm.input_messages.0.message.role": "tool",
                  "llm.input_messages.0.message.contents.1.message_content.text": "world",
                  "llm.input_messages.0.message.contents.0.message_content.text": "hello ",
                  "llm.input_messages.x.message.role": "ignored", "llm.other": 1}
    (message,) = parse_messages(attributes, "llm.input_messages")
    assert message.content == "hello world" and message.role == "tool"
