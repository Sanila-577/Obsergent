"""agent.py - the example 2 agent, now sending its traces to Langfuse.

Langfuse records every LangGraph step, every model call and every tool call.
Set your keys first (see .env.example), then:
    python agent.py "Do you have a Python book in stock, and how much is it?"

Only two things changed from example 2:
  1. a Langfuse CallbackHandler is passed to the agent (config={"callbacks": [...]})
  2. get_client().flush() runs before the program exits
"""
import asyncio  # MCP and LangGraph are async, so we need an event loop
import os  # to check whether the Langfuse keys are set
import sys  # sys.executable (this Python) and sys.argv (the question)

from langchain_mcp_adapters.client import MultiServerMCPClient  # starts MCP servers and connects to them
from langchain_mcp_adapters.tools import load_mcp_tools  # turns MCP tools into LangChain tools
from langfuse import get_client  # gives us the shared Langfuse client (used for flush)
from langfuse.langchain import CallbackHandler  # LangChain "listener" that reports every step to Langfuse
from langgraph.graph import START, MessagesState, StateGraph  # building blocks of the agent graph
from langgraph.prebuilt import ToolNode, tools_condition  # ready-made "run the tools" node + routing rule

from llm import get_llm  # fake or Ollama model, from llm.py

# How to start the MCP server: the agent launches it as a child process over stdio.
# Nothing is hosted; it lives only while the `async with client.session(...)` block below is open.
SERVERS = {
    "bookshop": {"transport": "stdio", "command": sys.executable, "args": ["bookshop_server.py"]}
}

# Instructions given to the model at the start of every conversation.
SYSTEM_PROMPT = (
    "You are a helpful bookshop assistant. Use the tools to look up books, "
    "prices and stock. Answer in one or two short sentences."
)


def build_graph(tools):
    """Same two-node graph as example 2: the model decides, the tool node acts, repeat."""
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
    # NEW (1/3): create the Langfuse listener. It reads LANGFUSE_PUBLIC_KEY,
    # LANGFUSE_SECRET_KEY and LANGFUSE_BASE_URL from the environment.
    langfuse_handler = CallbackHandler()
    client = MultiServerMCPClient(SERVERS)
    async with client.session("bookshop") as session:  # starts the server; one connection for the whole run
        tools = await load_mcp_tools(session)  # asks the server "tools/list" and converts the result
        agent = build_graph(tools)
        result = await agent.ainvoke(
            {"messages": [("system", SYSTEM_PROMPT), ("user", question)]},  # starting conversation
            # NEW (2/3): hand the listener to LangGraph. From now on LangChain calls it
            # at the start and end of every graph node, model call and tool call, and the
            # Langfuse SDK queues that data. run_name becomes the trace's name in the UI.
            config={"callbacks": [langfuse_handler], "run_name": "bookshop-agent"},
        )
    # NEW (3/3): Langfuse sends data in the background in batches. If the program exits
    # right away, the last batch could be lost, so flush() sends everything now.
    get_client().flush()
    # The last message is the model's final answer.
    return result["messages"][-1].content


if __name__ == "__main__":
    # Friendly hint: without keys the agent still runs, but nothing reaches Langfuse.
    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        print("Tip: set LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL first.")
    # Use the words typed after "python agent.py", or a default question if none.
    question = " ".join(sys.argv[1:]) or "Do you have a Python book in stock, and how much is it?"
    print(asyncio.run(run(question)))
