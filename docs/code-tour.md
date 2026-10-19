# AgentTrace code tour: how to study this program

This is the guide to read **before** opening the code. It explains the words, draws every path a message takes,
and gives a reading order with what to look for in each file. Every Python file under `src/agenttrace/` now has a
comment above (almost) every line; this tour tells you which file to open first and why.

---

## 1. Words you need (plain language)

| Word                                   | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                           |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **MCP** (Model Context Protocol) | A standard way for an AI app (the *client*) to ask a *server* "what tools do you have?" and "please run this tool".                                                                                                                                                                                                                                                                                                           |
| **JSON-RPC**                     | The message format MCP uses. A message is a small JSON object. Three kinds, see below.                                                                                                                                                                                                                                                                                                                                            |
| **stdio**                        | "Standard input/output". A program reads text from its *stdin* pipe and writes text to its *stdout* pipe. MCP over stdio = the client starts the server as a child process and they talk through these two pipes, one JSON message per line.                                                                                                                                                                                  |
| **HTTP / Streamable HTTP**       | The same JSON-RPC messages, but sent with web requests (`POST /mcp`). The reply is either plain JSON or an **SSE** stream (a response that keeps sending `data: {...}` lines).                                                                                                                                                                                                                                          |
| **gRPC**                         | A different way for two programs to call each other over a network. Instead of text JSON over HTTP/1, it sends compact binary messages (**protobuf**) over HTTP/2, and you call named functions ("RPC" = remote procedure call) like `TraceService.Export`. AgentTrace needs it for exactly one reason: the WSO2 gateway sends its telemetry to port 4317 (`server.grpc_port` in `config.yaml`) using gRPC, not HTTP. |
| **protobuf**                     | The binary format gRPC uses. Smaller and faster than JSON, but not human readable.                                                                                                                                                                                                                                                                                                                                                |
| **OpenTelemetry (OTel)**         | A standard for recording what a program does.                                                                                                                                                                                                                                                                                                                                                                                     |
| **span**                         | One recorded step: a name, start time, end time, status, extra details (*attributes*).                                                                                                                                                                                                                                                                                                                                          |
| **trace**                        | All spans of one run. They share a `trace_id`; each span points to its parent with `parent_span_id`, so they form a tree.                                                                                                                                                                                                                                                                                                     |
| **OTLP**                         | "OpenTelemetry Protocol": how spans travel from a program to a collector. It comes in two flavours: over HTTP (`POST /v1/traces`) and over gRPC (port 4317). AgentTrace accepts both.                                                                                                                                                                                                                                           |
| **traceparent**                  | A small text `00-<trace id>-<span id>-01` that says "I am part of this trace, under this span". Passing it along is how the agent, the proxy and the gateway end up in the *same* trace.                                                                                                                                                                                                                                      |
| **Proxy**                        | A program placed in the middle. The client talks to the proxy, the proxy forwards to the real server, and notes everything on the way.                                                                                                                                                                                                                                                                                            |
| **Gateway**                      | A proxy that also enforces rules (login, rate limits, which tools are allowed). WSO2 API Manager is one.                                                                                                                                                                                                                                                                                                                          |
| **SQLite**                       | A database stored in one file (`~/.agenttrace/agenttrace.db`). No server to install.                                                                                                                                                                                                                                                                                                                                            |
| **FastAPI / uvicorn**            | FastAPI is a Python web framework (you write functions, each becomes a URL). uvicorn is the program that actually listens on the port and runs it.                                                                                                                                                                                                                                                                                |
| **React / React Query**          | React draws the web page from data; React Query fetches that data from the API and caches it.                                                                                                                                                                                                                                                                                                                                     |

### The three JSON-RPC message kinds

```
request       {"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"search_books","arguments":{"query":"python"}}}
response      {"jsonrpc":"2.0","id":7,"result":{"content":[{"type":"text","text":"[...]"}]}}
              {"jsonrpc":"2.0","id":7,"error":{"code":-32601,"message":"Method not found"}}
notification  {"jsonrpc":"2.0","method":"notifications/initialized"}      <- no id, nobody answers
```

The `id` pairs an answer with its question. The recorder uses exactly that: a **request opens a span**, the
**response with the same id closes it**.

A normal MCP conversation:

```
client -> initialize          server -> (its name, capabilities)
client -> notifications/initialized
client -> tools/list          server -> (list of tools with descriptions)
client -> tools/call          server -> (the tool's result)     <- repeated many times
```

---

## 2. The whole program in one picture

```
 YOUR AGENT (examples/bookshop/agent.py)                               WEB BROWSER (React UI)
 ├─ SDK  at.init()  ── spans (OTLP/HTTP) ──────────┐                          ▲  GET /api/...
 └─ MCP client ──stdio──► PROXY ──stdio──► MCP SERVER (bookshop_server.py)    │
                           │  (cli.py proxy → proxy/stdio.py + recorder.py)   │
                           └── spans (OTLP/HTTP) ──┤                          │
                                                   ▼                          │
 CLAUDE DESKTOP / CURSOR ──stdio──► PROXY ...      AGENTTRACE SERVER  (cli.py up → server/app.py)
 AGENT ──HTTP──► HTTP PROXY ──HTTP──► WSO2 GATEWAY ──► MCP SERVER           │  POST /v1/traces      ← OTLP/HTTP
        (proxy/http.py)            │                                        │  gRPC :4317 (--grpc)  ← OTLP/gRPC (WSO2)
                                   └── its own spans (OTLP/gRPC) ──────────►│
                                                                            ▼
                                                  ingest/ (parse, normalize, snapshot) → storage/sqlite.py → analysis/
```

Three programs run: **the agent** (with the SDK and a proxy child process), **the AgentTrace server**, and
**the browser**. They only meet through the database file and the HTTP API.

---

## 3. Every path, step by step (with the code that runs)

### Path 0: starting the server — `agenttrace up`

1. You type `agenttrace up`. The command `agenttrace` exists because `pyproject.toml` says
   `agenttrace = "agenttrace.cli:main"` and `uv pip install -e .` creates a launcher for it.
2. `cli.py: main()` → `build_parser().parse_args()` reads the words → `COMMANDS["up"]` → `cmd_up()`.
3. `cmd_up` → `SQLiteStorage(config.db_path())`: opens the database file and runs `migrate()` (creates tables/views). The path, like every port, comes from `config.yaml` through `config.py`'s functions.
4. With `--grpc`: `server/grpc_receiver.py: start_grpc_server()` opens `config.grpc_port()` (4317) in background threads.
5. `uvicorn.run(create_app(storage))` → `server/app.py: create_app()` registers all URLs and blocks, serving forever.
6. Because `server/static/` holds the built UI, `/` returns `index.html` and the browser loads the React app.

### Path 1: your own agent — `python agent.py "Do you have a Python book?"`

1. `agent.py` imports; `at.init("bookshop-agent")` (`sdk/setup.py: init`) creates a tracer provider whose exporter sends
   batches of spans to `http://127.0.0.1:7318/v1/traces`, and switches on the LangChain/LangGraph auto-tracer
   (OpenInference): every graph step, model call and tool step becomes a span.
2. `run()` opens the root span `agent.run`.
3. `at.proxy_server("bookshop", [python, bookshop_server.py])` builds a connection description that starts
   **`python -m agenttrace.cli proxy --name bookshop -- python bookshop_server.py`** and puts the current trace id in
   the environment variable `MCP_PROXY_TRACEPARENT`.
4. `MultiServerMCPClient(...).session("bookshop")` launches that command. Now the **stdio proxy** is the child process
   and *it* launches the real server (`cli.py: cmd_proxy` → `proxy/stdio.py: StdioProxy.run`).
5. `at.trace_tool_calls(session)` wraps `session.call_tool` so each call carries `_meta.traceparent` = the id of the exact
   tool step that made it.
6. `agent.ainvoke(...)` runs the graph: model node → (model asks for a tool) → tool node → `call_tool` →
   a `tools/call` request goes down the pipe to the proxy → …
7. At the end `provider.shutdown()` flushes the last spans.

### Path 2: one MCP message through the stdio proxy

```
agent ──line──► proxy stdin ──pump──► Recorder.on_request ──► real server stdin
agent ◄─line─── proxy stdout ◄─pump── Recorder.on_response ◄── real server stdout
```

1. `StdioProxy.pump` reads one line, `json.loads` it, calls the handler, writes the line on.
2. **Request** → `Recorder.on_request` (`proxy/recorder.py`): starts a span named `tools/call search_books`; parent =
   the `traceparent` in `_meta` (the agent's tool step) so it joins the agent's trace; stores tool name and
   **redacted** arguments (`proxy/redact.py`); rewrites `_meta.traceparent` to this span; remembers it in `pending[id]`.
3. **Response** → `Recorder.on_response`: finds `pending[id]`, records the result (or `error`, or `isError`), calls
   `span.end()`. For `tools/list` it stores the whole tool list in `mcp.tools`.
4. Finished spans are queued by the `BatchSpanProcessor` and POSTed to the server (Path 4).
5. If anything in recording throws, the original line is forwarded unchanged — recording never breaks the agent.

### Path 3: the HTTP proxy and a WSO2 gateway — `agenttrace proxy-http`

```
client ──POST /mcp/<name>──► proxy/http.py ──POST (+traceparent)──► WSO2 gateway ──► MCP server
```

1. `forward()` reads the body, finds the JSON-RPC requests, calls `Recorder.on_request` for each (also adds the caller
   from the JWT: `proxy/identity.py`, never the token itself).
2. It sends the request upstream with the trace context in the `traceparent` header. WSO2 continues that trace.
3. The reply is plain JSON or SSE. Each JSON-RPC response goes to `Recorder.on_response`, with extra attributes from
   `proxy/gateway.py: outcome_attributes` — HTTP status, **decision** (allowed / unauthorized 401 / forbidden 403 /
   throttled 429 / denied / error), a hash of `Mcp-Session-Id`, and WSO2's `activityid` header.
4. Requests that got no JSON-RPC answer (a 401 page) are closed as errors by `close_ids`.

### Path 4: spans arrive at the server (OTLP over HTTP)

1. `POST /v1/traces` → `server/app.py: receive_otlp` (un-gzip if needed).
2. `ingest/otlp.py: parse_export_request` (protobuf) or `parse_export_json` → a plain list of `Span` objects
   (`models.py`). OTLP nests `resource_spans → scope_spans → spans`; this flattens it and copies the session attributes
   from the resource onto each span.
3. `ingest/pipeline.py: ingest_spans`: (a) `ingest/gateway.py` renames WSO2-specific attributes to AgentTrace ones and
   marks gateway spans `agenttrace.layer=gateway`; (b) `storage.save_spans` writes rows; (c) any `mcp.tools` list is saved
   as a **tool snapshot** (only if new) so changes can be detected.

### Path 4b: a full run through the gateway (verified)

```
agent.py (MCP_URL=http://127.0.0.1:7319/mcp/wso2)
  └─ at.init / LangGraph spans ───────────────────────────────► POST /v1/traces (HTTP)
  └─ tools/call ─HTTP─► proxy-http (proxy/http.py) ─HTTP+traceparent─► gateway :8080 ─► bookshop_http.py :9100
                          │ span + decision                          │ router + policy-engine spans
                          └─► POST /v1/traces                        └─► gRPC :4317 (server/grpc_receiver.py)
                                          both land in ingest_spans → SQLite, in ONE trace
```

The agent's `trace_tool_calls` puts the tool step's trace id in the request; the proxy makes its span a child of it and
forwards its own id in the `traceparent` header; the gateway continues that trace. Result in the UI:
`agent.run → LangGraph → tools → search_books → tools/call (proxy) → ingress (gateway) → policy engine / backend`.

### Path 5: spans arrive over gRPC (WSO2 gateway telemetry)

WSO2 → gRPC call `TraceService.Export` on port 4317 → `server/grpc_receiver.py: TraceReceiver.Export` → the *same*
`spans_from_request` + `ingest_spans` as Path 4. Only the door differs; everything after is shared.

### Path 6: the browser reads data

1. Browser opens `http://127.0.0.1:7318/` → `serve_ui` returns `index.html` → `ui/src/main.tsx` starts React.
2. `App.tsx` maps the URL to a page; `components/Layout.tsx` draws the menu.
3. A page calls `useQuery(... api.something())` → `api/client.ts: request()` → `fetch("/api/...")`.
4. `server/app.py` handles it: reads from `storage/sqlite.py` and/or `analysis/*`, returns JSON. React draws it.
5. In Live mode, React Query re-fetches every 2 seconds.

### Path 6b: the cost of a model call

Costs are never stored on spans: they are calculated when something asks for them.

0. **The provider's own charge:** when a span arrives, `ingest/billed.py` (called from `ingest/pipeline.py`) digs OpenRouter's `usage.cost` or xAI's `cost_in_usd_ticks` out of the recorded response and stores it as `llm.cost.total`, plus facts the formula needs (service tier, 1-hour cache writes, web searches).
1. **Prices in:** `cmd_up` → `server/price_sync.py: start_background_refresh` downloads four public price lists
   (models.dev, OpenRouter, Hugging Face, LiteLLM) in a background thread, with ETag so unchanged lists are skipped; each
   parser turns its list into rows (`provider, model, input, output, cache_read, cache_write` per million tokens);
   `storage/sqlite.py: save_prices` adds a row only when a price changed (a history).
2. **A page asks:** e.g. `GET /api/traces` or `/api/spending` in `server/app.py` → `server/costing.py: CostCalculator`.
3. **Per model call:** `analysis/generations.py: to_generation` reads the token counts (and cached/reasoning counts) from the span,
   `server/costing.py` loads the price rows for that model, and `analysis/pricing.py: cost_of_call` decides: a cost the provider
   reported, a local model ($0), the price (router's list first, then models.dev, then LiteLLM) and the formula, or "no price".
4. **Totals:** `pricing.sum_costs`; the Spending page data comes from `costing.spending` (by model, by tool, over time, top runs).
5. **UI:** `ui/src/pages/Spending.tsx`, `components/CostRibbon.tsx`, `components/Money.tsx`.

Full explanation: [costs.md](costs.md).

### Path 7: the command line reading data — `agenttrace traces | show | sessions | drift`

`cli.py` opens the SQLite file directly (no server needed) and prints.

---

## 4. File by file (read in this order)

Each line tells you *what the file is for* and *what to look for*.

### A. The vocabulary (5 minutes)

1. `config.yaml` (repository root) — every port, address and path, with a comment on each. Then `src/agenttrace/config.py`: it loads that file once and answers through functions (`port()`, `grpc_port()`, `endpoint()`, `db_path()`, `proxy_port()`, `gateway_router()`, ...). Precedence: environment variable, then the YAML, then the built-in default. `agenttrace config` prints what is in use.
2. `src/agenttrace/models.py` — the one `Span` class everything uses. Read every field.

### B. Recording (the proxy)

3. `proxy/redact.py` — secret hiding. Look at `redact()` (recursive) and `safe_command()`.
4. `proxy/sessions.py` — `Session` and `make_provider()`: how a proxy process gets an id and an exporter.
5. `proxy/recorder.py` — **the most important file.** Follow `pending`: filled in `on_request`, emptied in `on_response`.
6. `proxy/stdio.py` — the two `pump` tasks and the child process.
7. `proxy/gateway.py` — `classify()`: a table from HTTP status to decision.
8. `proxy/identity.py` — read a JWT payload (never verify, never keep).
9. `proxy/http.py` — `forward()`: the same recorder, over HTTP, with JSON and SSE branches.
10. `sdk/setup.py` — what the agent calls: `init`, `context`, `trace_tool_calls`, `proxy_server`.

### C. Receiving

11. `ingest/otlp.py` — decode OTLP (protobuf/JSON) into `Span`s.
12. `ingest/gateway.py` — translate WSO2's span vocabulary into AgentTrace's.
13. `ingest/pipeline.py` — `ingest_spans`: normalize → save → remember tool lists. Then, for costs: `server/price_sync.py` (download prices), `analysis/pricing.py` (the formula, pure functions) and `server/costing.py` (glue to the database).
14. `server/grpc_receiver.py` — the gRPC door.

### D. Storage

15. `storage/base.py` — the *list of methods* a database must have (no logic).
16. `storage/sqlite.py` — read `SCHEMA_V1…V4` first (tables and views), then `save_spans`, then `list_traces`.
    SQL is explained clause by clause in comments.

### E. Analysis (pure functions over spans — easiest to test)

17. `analysis/stats.py` → `smells.py` → `diff.py` → `safety.py` → `toolsdiff.py` → `policy.py` → `generations.py` →
    `findings.py` → `gateway_view.py`.

### F. The server

18. `server/app.py` — one function per URL. Skim the section headers (`# ---- runs`, `# ---- findings`, …).
19. `cli.py` — the commands and how they map to the pieces above.

### G. The example

20. `examples/bookshop/bookshop_server.py` (a tiny MCP server), `llm.py`, `agent.py`.

### H. The UI (after you know the API)

21. `ui/src/main.tsx` → `App.tsx` → `api/client.ts` → `lib/state.tsx` → `components/Layout.tsx`.
22. `pages/Runs.tsx` → `pages/RunDetail.tsx` → `components/Waterfall.tsx` + `lib/trace.ts` (the tree and timeline maths).
23. The other pages (`Overview`, `Sessions`, `Servers`, `Findings`, `Gateway`, `MapPage`, `Compare`) all follow the same
    pattern: `useQuery` → API → draw. Their logic is small; read them when you want to see a feature.

### I. Tests (how each piece is proven)

`tests/test_recorder.py` (the pending table), `test_stdio_proxy.py`, `test_http_proxy.py`, `test_wso2_gateway.py`,
`test_ingest_and_api.py`, `test_ui_api.py`. A test shows the expected input/output of a file better than prose.

---

## 5. Try it to *see* the flow

```bash
# 0. once: uv venv; source .venv/bin/activate; uv pip install -e ".[dev,langchain,examples,grpc]"; make ui-build; make env
#    (skip the activation if an environment is already active; `make help` lists the Makefile targets)

# 1. start the server (Terminal 1)
make up

# 2. run the agent with a question you type (Terminal 2; model from .env, default Ollama qwen2.5:7b)
cd examples/bookshop && python agent.py "<your question>"

# 3. look at what was recorded
make traces                # one line per run
agenttrace show <id>       # the span tree of a run
# 4. open http://127.0.0.1:7318 and click the run
```

To watch a single request move: put `print(msg, file=sys.stderr)` at the top of `Recorder.on_request` and
`on_response` (stderr, never stdout) and run step 2 — you will see every JSON-RPC message in order.
