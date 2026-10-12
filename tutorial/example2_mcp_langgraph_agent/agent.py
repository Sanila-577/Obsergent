"""agent.py - a LangGraph agent that uses the Bookshop MCP server's tools.

    python agent.py "Do you have a Python book in stock, and how much is it?"
    python view.py          # see the client + server spans as one tree
"""
import asyncio  # MCP and LangGraph are async, so we need an event loop
import os  # to read the MCP_TRACING environment variable
import sys  # for sys.executable (this Python) and sys.argv (the question)

from langchain_mcp_adapters.client import MultiServerMCPClient  # starts MCP servers and connects to them
from langchain_mcp_adapters.tools import load_mcp_tools  # turns MCP tools into LangChain tools
from langgraph.graph import START, MessagesState, StateGraph  # building blocks of the agent graph
from langgraph.prebuilt import ToolNode, tools_condition  # ready-made "run the tools" node + routing rule
from opentelemetry import trace  # to create our own spans

from llm import get_llm  # fake or Ollama model, from llm.py

TRACING = os.environ.get("MCP_TRACING", "1") != "0"  # MCP_TRACING=0 switches tracing off

if TRACING:
    from mcp_tracing import trace_client_session  # client-side MCP spans
    from tracker import setup_tracing  # Example 1's SQLite exporter

    setup_tracing("bookshop-agent")  # this program's spans -> traces.db

# Gets a tracer from the provider configured above (or a no-op one if tracing is off).
tracer = trace.get_tracer("bookshop-agent")

# How to start each MCP server. The agent launches it as a child process.
SERVERS = {
    "bookshop": {  # our own name for this server
        "transport": "stdio",  # talk over the child's stdin/stdout
        "command": sys.executable,  # run with the same Python that runs the agent
        "args": ["bookshop_server.py"],  # the script to start (relative to the current folder)
    }
}

# Instructions given to the model at the start of every conversation.
SYSTEM_PROMPT = (
    "You are a helpful bookshop assistant. Use the tools to look up books, "
    "prices and stock. Answer in one or two short sentences."
)


def build_graph(tools):
    """Two nodes: the model decides, the tool node acts. Loop until the model answers."""
    llm = get_llm().bind_tools(tools)  # tell the model which tools it may call

    async def call_model(state: MessagesState):
        # state["messages"] is the whole conversation so far (system, user, AI, tool messages).
        reply = await llm.ainvoke(state["messages"])
        return {"messages": [reply]}  # LangGraph appends this reply to the conversation

    graph = StateGraph(MessagesState)  # a graph whose state is a list of messages
    graph.add_node("agent", call_model)  # node 1: the model thinks
    graph.add_node("tools", ToolNode(tools))  # node 2: runs the tools the model asked for
    graph.add_edge(START, "agent")  # always begin with the model
    graph.add_conditional_edges("agent", tools_condition)  # tool call? -> "tools", else -> END
    graph.add_edge("tools", "agent")  # after tools run, go back to the model with the results
    return graph.compile()  # turn the description into a runnable agent


async def run(question: str) -> str:
    client = MultiServerMCPClient(SERVERS)
    async with client.session("bookshop") as session:  # one MCP connection for the whole run
        if TRACING:
            trace_client_session(session)  # every MCP request from here on gets a span
        tools = await load_mcp_tools(session)  # asks the server "tools/list" and converts the result
        agent = build_graph(tools)
        result = await agent.ainvoke(
            {"messages": [("system", SYSTEM_PROMPT), ("user", question)]}  # starting conversation
        )
    # The last message is the model's final answer.
    return result["messages"][-1].content


async def main(question: str) -> str:
    # Root span: every MCP client span below becomes part of this one trace.
    with tracer.start_as_current_span("agent.run") as span:
        span.set_attribute("agent.question", question)  # store what was asked
        return await run(question)


if __name__ == "__main__":
    # Use the words typed after "python agent.py", or a default question if none.
    question = " ".join(sys.argv[1:]) or "Do you have a Python book in stock, and how much is it?"
    print(asyncio.run(main(question)))
