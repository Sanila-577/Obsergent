# Example 4: OpenTelemetry inside the agent

Goal: produce the same kind of trace as Langfuse (Example 3), but with plain
OpenTelemetry, stored in **your own** tracker from Example 1. This is the
"inside the agent" half of AgentTrace.

## Files

| File | Purpose |
|---|---|
| `agent.py` | The agent + three tracing additions (marked 1, 2, 3 in the comments) |
| `tracker.py` | Copied from Example 1: finished spans -> SQLite (`traces.db`) |
| `view.py` | Copied from Example 1: prints traces as trees |
| `bookshop_server.py` | Same MCP server as before (no tracing code) |
| `llm.py` | Ollama model, or `FAKE_LLM=1` scripted stand-in |

## How it works

```
python agent.py
   │
   ▼
setup_tracing("bookshop-agent")        1. spans will be written to traces.db
   │
LangChainInstrumentor().instrument()   2. hooks LangChain's callbacks: every graph node,
   │                                      model call and tool call becomes a span
   ▼
with tracer.start_as_current_span("agent.run")      3. root span: one trace per run
   │
   ├─ starts bookshop_server.py (child process, stdio, nothing to host)
   ├─ LangGraph runs: agent node ⇄ tools node         -> spans created automatically
   ▼
every finished span ─► SQLiteSpanExporter ─► traces.db ─► python view.py
```

Compared with Example 3: no Langfuse account, keys or network. The same
information goes into a SQLite file you own.

The three additions to Example 2's agent:

1. `setup_tracing("bookshop-agent")`: our SQLite exporter from Example 1.
2. `LangChainInstrumentor().instrument(...)`: creates spans for every LangGraph
   node, model call and tool step, following the OpenInference conventions.
3. A root span `agent.run`, so the whole run is one trace, with the question and
   answer stored as attributes.

## Run it

From the repository root, with the virtual environment active and the requirements
installed (`uv pip install -r requirements.txt`):

```bash
cd tutorial/example4_otel_agent
FAKE_LLM=1 python agent.py          # without Ollama (scripted stand-in model)
# python agent.py                   # with Ollama (ollama pull qwen2.5:7b first)
python view.py
```

Expected `view.py` output: 15 spans in one trace (timings vary):

```
Trace 66200f004179...  (15 spans)
  - agent.run  (bookshop-agent, 755.9 ms)
    - LangGraph  (bookshop-agent, 55.6 ms)
      - agent  (bookshop-agent, 9.8 ms)
        - ScriptedFakeLLM  (bookshop-agent, 1.7 ms)
        - tools_condition  (bookshop-agent, 0.7 ms)
      - tools  (bookshop-agent, 11.4 ms)
        - search_books  (bookshop-agent, 5.9 ms)
      - agent  (bookshop-agent, 5.9 ms)
        - ScriptedFakeLLM  (bookshop-agent, 1.1 ms)
        - tools_condition  (bookshop-agent, 0.5 ms)
      - tools  (bookshop-agent, 8.5 ms)
        - get_price_and_stock  (bookshop-agent, 5.7 ms)
      - agent  (bookshop-agent, 6.9 ms)
        - ScriptedFakeLLM  (bookshop-agent, 1.3 ms)
        - tools_condition  (bookshop-agent, 1.0 ms)
```

Reading the tree: the graph ran `agent` (model asks for `search_books`), `tools`
(runs it), `agent` (asks for `get_price_and_stock`), `tools`, then `agent` again
(the final answer). Delete `traces.db` to start fresh.

## Look at the details

The tree shows names and timings. The inputs and outputs are stored too, as span
attributes (OpenInference names `input.value`, `output.value`, `tool.name`,
`openinference.span.kind`):

```bash
sqlite3 traces.db "SELECT name,
  json_extract(attributes,'\$.\"openinference.span.kind\"') AS kind,
  json_extract(attributes,'\$.\"input.value\"')  AS input
  FROM spans WHERE name IN ('search_books','get_price_and_stock')"
```

## What is still missing

Look at the tree: the MCP messages themselves (`initialize`, `tools/list`, the
raw `tools/call` with its arguments and result) are not there. This example only
sees what happens inside the agent. The other half, the MCP traffic, comes next:
Example 5 adds a proxy that records it and joins it to this same trace.

## Try this

- Run the agent several times and compare the traces (each run is its own trace).
- Ask about a book that doesn't exist and find the error in the tool span's output.
- Compare this tree with the Langfuse trace from Example 3.
