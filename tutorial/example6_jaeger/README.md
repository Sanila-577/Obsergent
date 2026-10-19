# Example 6: sending everything to Jaeger

Goal: prove OpenTelemetry's promise. **Swap the backend by replacing one file.**
The agent, proxy and server code stay the same as Example 5; only the exporter
changes from SQLite to OTLP, and Jaeger shows the same trace in a web UI.

## Files

| File | Purpose |
|---|---|
| `docker-compose.yml` | Runs Jaeger v2 (UI on 16686, OTLP/HTTP on 4318) |
| `otel_setup.py` | **New.** `setup_tracing()` with an OTLP exporter (replaces `tracker.py`) |
| `agent.py` | Example 5's agent; imports `otel_setup` and calls `provider.shutdown()` at the end |
| `mcp_proxy.py` | Example 5's proxy; the only change is `from otel_setup import setup_tracing` |
| `trace_context.py`, `bookshop_server.py`, `llm.py` | Unchanged from Example 5 |

`tracker.py` and `view.py` are not needed any more: Jaeger stores and shows the spans.

## What changed compared with Example 5

| | Example 5 | Example 6 |
|---|---|---|
| Span destination | `tracker.py`: `SimpleSpanProcessor` + SQLite exporter | `otel_setup.py`: `BatchSpanProcessor` + OTLP/HTTP exporter |
| Where to look | `python view.py` | Jaeger UI at http://localhost:16686 |
| Proxy and agent need the DB path | yes (`TRACKER_DB`) | no, both send over the network |
| Before exiting | nothing | `provider.shutdown()` sends the last batch |

## How it works

```
python agent.py ──starts──► mcp_proxy.py ──starts──► bookshop_server.py
   │ spans (service bookshop-agent)   │ spans (service mcp-proxy)
   │                                  │
   └──────────── OTLP / HTTP ─────────┴──► http://localhost:4318/v1/traces
                                                    │
                                          Jaeger (docker container)
                                                    │
                                          UI: http://localhost:16686
```

Both programs send **to the same endpoint**. They end up in one trace because the
trace ID is passed from the agent to the proxy exactly as in Example 5.

## Run it

**1. Start Jaeger** (needs Docker running):

```bash
cd tutorial/example6_jaeger
docker compose up -d          # first run downloads the image
```

**2. Run the agent** (virtual environment active, requirements installed; the OTLP exporter is in `requirements.txt`):

```bash
FAKE_LLM=1 python agent.py    # without Ollama; use plain `python agent.py` with Ollama
```

**3. Open the UI:** http://localhost:16686 -> **Service:** `bookshop-agent` -> **Find Traces** -> click the trace.

You should see one trace with 19 spans from 2 services (`bookshop-agent` and
`mcp-proxy`): the LangGraph steps with the proxy's `tools/call ...` spans nested under
the tool steps, plus `initialize` and `tools/list`. Click a `tools/call` span to see
its tags: `gen_ai.tool.name`, `mcp.tool.arguments`, `mcp.result`.

**4. Stop Jaeger** when done: `docker compose down`. Jaeger keeps traces in memory, so they are gone after that.

## Troubleshooting

- **"Connection refused" / no traces:** Jaeger isn't running. Check `docker compose ps` and that port 4318 is free.
- **Only the first part of the trace:** the program exited before the batch was sent. Every program must call `provider.shutdown()`; the agent does it in `agent.py`, the proxy at the end of `main()`.
- **Different Jaeger or another OTLP backend:** `export OTEL_EXPORTER_OTLP_ENDPOINT=http://host:4318` before running (the proxy inherits it).

## What you have now

The same spans could go to Jaeger, Langfuse **and** your SQLite tracker at once:
add more span processors to the provider (`provider.add_span_processor(...)`). That
is how Obsergent will coexist with other tools.

## Try this

- Compare this trace with `python view.py` output from Example 5: same spans, different viewer.
- In Jaeger, open the "Trace Timeline" and find the slowest span (probably `initialize`: the server start-up).
- In `otel_setup.py`, add a second `BatchSpanProcessor` with `ConsoleSpanExporter` and watch the spans also print in the terminal.
