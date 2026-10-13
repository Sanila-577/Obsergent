"""agent.py - the same agent, traced with OpenTelemetry into our own tracker.

Instead of Langfuse (example 3), the spans go to the SQLite tracker from example 1.
    python agent.py "Do you have a Python book in stock, and how much is it?"
    python view.py

Three things are added compared with example 2:
  1. setup_tracing(...)               our SQLite exporter from example 1
  2. LangChainInstrumentor()...       auto-creates a span for every LangGraph node,
                                      model call and tool call
  3. a root span "agent.run"          so the whole run lands in ONE trace
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
from tracker import setup_tracing  # Example 1: finished spans -> SQLite (traces.db)

# 1. Send this program's spans to traces.db.
#    setup_tracing() builds an OpenTelemetry TracerProvider whose exporter writes
#    to SQLite, and returns that provider so we can hand it to the instrumentor.
provider = setup_tracing("bookshop-agent")

# 2. Auto-create spans for every LangGraph node, model call and tool call.
#    The instrumentor hooks into LangChain's callback system (the same hook
#    Langfuse used in example 3) and turns each callback into an OpenTelemetry
#    span, named following the OpenInference conventions. We write NO span code
#    for the graph ourselves: this one line does it.
LangChainInstrumentor().instrument(tracer_provider=provider)

# A tracer for the spans we create by hand (only the root span below).
tracer = trace.get_tracer("bookshop-agent")

# How to start the MCP server: the agent launches it as a child process over stdio.
# Nothing is hosted; it lives only while the `async with client.session(...)` block is open.
SERVERS = {
    "bookshop": {"transport": "stdio", "command": sys.executable, "args": ["bookshop_server.py"]}
}

# Instructions given to the model at the start of every conversation.
SYSTEM_PROMPT = (
    "You are a helpful bookshop assistant. Use the tools to look up books, "
    "prices and stock. Answer in one or two short sentences."
)


def build_graph(tools):
    """Same two-node graph as example 2. Note: no tracing code in here at all."""
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
    # 3. One root span for the whole run, so everything lands in one trace.
    #    Spans the instrumentor creates while this block is open become its
    #    children (same trace ID), which is why view.py shows a single tree.
    with tracer.start_as_current_span("agent.run") as span:
        span.set_attribute("agent.question", question)  # store what was asked
        client = MultiServerMCPClient(SERVERS)
        async with client.session("bookshop") as session:  # starts the server; one connection for the whole run
            tools = await load_mcp_tools(session)  # asks the server "tools/list" and converts the result
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
    print("Trace saved. Run: python view.py")
