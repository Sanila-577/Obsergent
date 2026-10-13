"""agent.py - example 5's agent, now sending everything to Jaeger.

Agent spans (LangGraph, model, tools) and proxy spans (every MCP message)
are sent over OTLP to Jaeger and join into one trace.
    docker compose up -d
    python agent.py "Do you have a Python book in stock, and how much is it?"
    # open http://localhost:16686, choose service 'bookshop-agent', click Find Traces

Compared with example 5 only two things change:
  1. setup_tracing comes from otel_setup.py (OTLP -> Jaeger) instead of tracker.py (SQLite)
  2. the agent calls provider.shutdown() before exiting, to send the last batch
"""
import asyncio  # MCP and LangGraph are async, so we need an event loop
import sys  # sys.executable (this Python) and sys.argv (the question)

from langchain_mcp_adapters.client import MultiServerMCPClient  # starts MCP servers and connects to them
from langchain_mcp_adapters.tools import load_mcp_tools  # turns MCP tools into LangChain tools
from langgraph.graph import START, MessagesState, StateGraph  # building blocks of the agent graph
from langgraph.prebuilt import ToolNode, tools_condition  # ready-made "run the tools" node + routing rule
from openinference.instrumentation.langchain import LangChainInstrumentor  # auto-tracing for LangChain/LangGraph
from opentelemetry import trace  # to create our own spans

from llm import get_llm  # fake or Ollama model, from llm.py
from otel_setup import setup_tracing  # CHANGED: spans -> Jaeger over OTLP (was tracker.py -> SQLite)
from trace_context import add_trace_context, proxy_env  # hand the trace ID to the proxy (as in example 5)

# Same as example 5, except where the spans go: this program's spans are sent to Jaeger,
# and LangGraph is auto-traced.
provider = setup_tracing("bookshop-agent")
LangChainInstrumentor().instrument(tracer_provider=provider)
tracer = trace.get_tracer("bookshop-agent")

# Instructions given to the model at the start of every conversation.
SYSTEM_PROMPT = (
    "You are a helpful bookshop assistant. Use the tools to look up books, "
    "prices and stock. Answer in one or two short sentences."
)


def servers() -> dict:
    """Start the real server through the proxy: proxy -- <real server command>."""
    return {
        "bookshop": {
            "transport": "stdio",
            "command": sys.executable,
            # The agent now starts the PROXY. Everything after "--" is the real server,
            # which the proxy starts itself. To the adapter, the proxy IS the server.
            "args": ["mcp_proxy.py", "--", sys.executable, "bookshop_server.py"],
            # Environment for the proxy process:
            #  - MCP_PROXY_TRACEPARENT: the agent's current trace (parent for initialize, tools/list)
            # (No TRACKER_DB any more: the proxy sends to Jaeger on its own, using the same
            # OTEL_EXPORTER_OTLP_ENDPOINT it inherits from this environment.)
            "env": proxy_env(),
        }
    }


def build_graph(tools):
    """Same two-node graph as before. No tracing code in here."""
    llm = get_llm().bind_tools(tools)  # tell the model which tools it may call

    async def call_model(state: MessagesState):
        # Send the whole conversation to the model and append its reply to the state.
        return {"messages": [await llm.ainvoke(state["messages"])]}

    graph = StateGraph(MessagesState)  # a graph whose state is a list of messages
    graph.add_node("agent", call_model)  # node 1: the model thinks
    graph.add_node("tools", ToolNode(tools))  # node 2: runs the tools the model asked for
    graph.add_edge(START, "agent")  # always begin with the model
    graph.add_conditional_edges("agent", tools_condition)  # tool call? -> "tools", else -> END
    graph.add_edge("tools", "agent")  # after the tools run, go back to the model with the results
    return graph.compile()  # turn the description into a runnable agent


async def run(question: str) -> str:
    # Root span for the whole run (as in example 4).
    with tracer.start_as_current_span("agent.run") as span:
        span.set_attribute("agent.question", question)  # store what was asked
        # IMPORTANT: servers() is called INSIDE the span, so proxy_env() captures
        # agent.run as the current span and gives it to the proxy as its session parent.
        client = MultiServerMCPClient(servers())
        async with client.session("bookshop") as session:  # starts proxy -> proxy starts the server
            # NEW: every tools/call now carries the traceparent of the exact tool step
            # that made it, so the proxy span nests under that step in the tree.
            add_trace_context(session)
            tools = await load_mcp_tools(session)  # tools/list goes through the proxy too
            agent = build_graph(tools)
            result = await agent.ainvoke(
                {"messages": [("system", SYSTEM_PROMPT), ("user", question)]}  # starting conversation
            )
        # The last message is the model's final answer.
        answer = result["messages"][-1].content
        span.set_attribute("agent.answer", answer)  # store the answer on the root span too
        return answer


if __name__ == "__main__":
    # Use the words typed after "python agent.py", or a default question if none.
    question = " ".join(sys.argv[1:]) or "Do you have a Python book in stock, and how much is it?"
    print(asyncio.run(run(question)))
    # NEW: the BatchSpanProcessor sends spans every few seconds. shutdown() sends what is
    # still waiting, otherwise the end of the run would be missing in Jaeger.
    provider.shutdown()
    print("Trace sent. Open http://localhost:16686, choose service 'bookshop-agent', click Find Traces")
