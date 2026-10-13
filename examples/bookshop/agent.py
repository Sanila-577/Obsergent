"""A LangGraph + Ollama agent traced by AgentTrace (SDK + proxy).

    agenttrace up                 # in another terminal: starts the server
    python agent.py "Do you have a Python book in stock?"
    agenttrace traces
    FAKE_LLM=1 python agent.py    # without Ollama: a scripted stand-in model

Two recorders feed the AgentTrace server:
  * the SDK  (at.init)        records the inside of the agent: LangGraph steps, model calls
  * the proxy (proxy_server)  records every MCP message between the agent and the server
Both join into ONE trace through the W3C trace context.
"""
import asyncio
import sys

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from llm import get_llm
from opentelemetry import trace

from agenttrace.sdk import setup as at  # the SDK: init(), proxy_server(), trace_tool_calls()

# 1. Spans -> AgentTrace server (http://127.0.0.1:7318), and LangGraph is auto-traced.
provider = at.init("bookshop-agent")
tracer = trace.get_tracer("bookshop-agent")

SYSTEM_PROMPT = (
    "You are a helpful bookshop assistant. Use the tools to look up books, "
    "prices and stock. Answer in one or two short sentences."
)


def build_graph(tools):
    """Same two-node graph as the tutorial: the model decides, the tool node acts, repeat."""
    llm = get_llm().bind_tools(tools)  # tell the model which tools it may call

    async def call_model(state: MessagesState):
        return {"messages": [await llm.ainvoke(state["messages"])]}  # reply is appended to the conversation

    g = StateGraph(MessagesState)
    g.add_node("agent", call_model)  # node 1: the model thinks
    g.add_node("tools", ToolNode(tools))  # node 2: runs the tools the model asked for
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", tools_condition)  # tool call? -> "tools", else -> END
    g.add_edge("tools", "agent")  # after the tools run, back to the model
    return g.compile()


async def run(question: str) -> str:
    # 2. One root span for the whole run: every span below becomes part of this trace.
    with tracer.start_as_current_span("agent.run"):
        # 3. Start the MCP server THROUGH the AgentTrace proxy. Built inside the root span,
        #    so the proxy is told which trace it belongs to (MCP_PROXY_TRACEPARENT).
        servers = {"bookshop": at.proxy_server("bookshop", [sys.executable, "bookshop_server.py"])}
        async with MultiServerMCPClient(servers).session("bookshop") as session:
            at.trace_tool_calls(session)  # 4. every tools/call carries the id of the tool step that made it
            agent = build_graph(await load_mcp_tools(session))
            result = await agent.ainvoke({"messages": [("system", SYSTEM_PROMPT), ("user", question)]})
        return result["messages"][-1].content


if __name__ == "__main__":
    print(asyncio.run(run(" ".join(sys.argv[1:]) or "Do you have a Python book in stock?")))
    provider.shutdown()  # send the last batch of spans before exiting
