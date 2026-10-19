"""A LangGraph + Ollama agent traced by Obsergent (SDK + proxy).

    obsergent up                 # in another terminal: starts the server
    python agent.py "Do you have a Python book in stock?"
    obsergent traces
    # the model comes from .env (copy .env.example): Ollama, OpenAI, Anthropic, Groq, OpenRouter, Hugging Face, ...

Two recorders feed the Obsergent server:
  * the SDK  (at.init)        records the inside of the agent: LangGraph steps, model calls
  * the proxy (proxy_server)  records every MCP message between the agent and the server
Both join into ONE trace through the W3C trace context.
"""
# asyncio runs the async agent.
import asyncio

# os reads the MCP_URL environment variable.
import os

# sys: command-line words and the path of the running Python.
import sys

# MultiServerMCPClient starts MCP servers and talks to them.
from langchain_mcp_adapters.client import MultiServerMCPClient

# load_mcp_tools turns an MCP server's tools into LangChain tools.
from langchain_mcp_adapters.tools import load_mcp_tools

# LangGraph pieces to build the agent as a graph of steps.
from langgraph.graph import START, MessagesState, StateGraph

# ToolNode runs requested tools; tools_condition decides "run tools or finish".
from langgraph.prebuilt import ToolNode, tools_condition

# llm.py: picks the language model (Ollama by default, or any provider chosen in .env).
from llm import get_llm

# OpenTelemetry API for making our own root span.
from opentelemetry import trace

# The Obsergent SDK.
from obsergent.sdk import setup as at  # the SDK: init(), proxy_server(), trace_tool_calls()

# 1. Spans -> Obsergent server (http://127.0.0.1:7318), and LangGraph is auto-traced.
provider = at.init("bookshop-agent")
# A tracer for the one span we create by hand.
tracer = trace.get_tracer("bookshop-agent")

# Instructions that tell the model how to behave.
SYSTEM_PROMPT = (
    "You are a helpful bookshop assistant. Use the tools to look up books, "
    "prices and stock. Answer in one or two short sentences."
)


# Build the agent: model node <-> tool node.
def build_graph(tools):
    """Same two-node graph as the tutorial: the model decides, the tool node acts, repeat."""
    # The model, told which tools exist.
    llm = get_llm().bind_tools(tools)  # tell the model which tools it may call

    # Node 1 body: send the conversation to the model.
    async def call_model(state: MessagesState):
        return {"messages": [await llm.ainvoke(state["messages"])]}  # reply is appended to the conversation

    # An empty graph whose state is the list of messages.
    g = StateGraph(MessagesState)
    # Add node 1.
    g.add_node("agent", call_model)  # node 1: the model thinks
    # Add node 2.
    g.add_node("tools", ToolNode(tools))  # node 2: runs the tools the model asked for
    # Start at the model.
    g.add_edge(START, "agent")
    # After the model: tool request -> tools node, otherwise end.
    g.add_conditional_edges("agent", tools_condition)  # tool call? -> "tools", else -> END
    # After the tools: ask the model again.
    g.add_edge("tools", "agent")  # after the tools run, back to the model
    # Finish building; the result can be run.
    return g.compile()


# One complete run of the agent for a question.
async def run(question: str) -> str:
    # 2. One root span for the whole run: every span below becomes part of this trace.
    with tracer.start_as_current_span("agent.run"):
        # 3. Start the MCP server THROUGH the Obsergent proxy. Built inside the root span,
        #    so the proxy is told which trace it belongs to (MCP_PROXY_TRACEPARENT).
        # With MCP_URL set (for example http://127.0.0.1:7319/mcp/wso2) the agent instead talks Streamable HTTP to that
        # URL: the Obsergent HTTP proxy in front of a gateway. Without it: the stdio server through the stdio proxy.
        if os.environ.get("MCP_URL"):
            servers = {"bookshop": {"transport": "streamable_http", "url": os.environ["MCP_URL"]}}
        else:
            servers = {"bookshop": at.proxy_server("bookshop", [sys.executable, "bookshop_server.py"])}
        # Start the server (through the proxy) and open a session to it.
        async with MultiServerMCPClient(servers).session("bookshop") as session:
            # Make every tools/call carry the trace context.
            at.trace_tool_calls(session)  # 4. every tools/call carries the id of the tool step that made it
            # Fetch the server's tools and build the agent around them.
            agent = build_graph(await load_mcp_tools(session))
            # 5. Optional: tag everything inside the block, so runs can be grouped by user and chat session.
            with at.context(session_id="bookshop-demo", user_id="demo-user"):
                # RUN: system prompt + question go in, the final messages come out.
                result = await agent.ainvoke({"messages": [("system", SYSTEM_PROMPT), ("user", question)]})
        # The last message is the answer.
        return result["messages"][-1].content


# Runs only when started with `python agent.py`.
if __name__ == "__main__":
    # The question comes from the command line: there is no built-in one.
    if len(sys.argv) < 2:
        sys.exit('usage: python agent.py "<your question>"')
    # Run the agent and print its answer.
    print(asyncio.run(run(" ".join(sys.argv[1:]))))
    # Flush the last batch of spans.
    provider.shutdown()  # send the last batch of spans before exiting
