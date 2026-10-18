# Example 3: tracking the agent with Langfuse

Goal: see what a mature, ready-made platform shows, so you know what "good"
looks like before we build our own. The agent is the same as Example 2; only
two small things are added to connect it to [Langfuse](https://langfuse.com).

## Files

| File                   | Purpose                                                                                          |
| ---------------------- | ------------------------------------------------------------------------------------------------ |
| `agent.py`           | Example 2's agent + Langfuse`CallbackHandler` and `flush()` (marked `NEW` in the comments) |
| `.env.example`       | Template for your Langfuse keys and URL                                                          |
| `bookshop_server.py` | Same MCP server as Example 2, without tracing code                                               |
| `llm.py`             | Ollama model, or`FAKE_LLM=1` scripted stand-in                                                 |

## How it works

```
python agent.py
   │
   ▼
agent.py ── starts ──► bookshop_server.py        (child process, stdio; nothing to host)
   │
   │  LangGraph runs:  agent node ⇄ tools node
   │  at every step LangChain calls the Langfuse CallbackHandler
   ▼
Langfuse SDK (OpenTelemetry inside) batches the data in the background
   │  get_client().flush() sends the last batch before exit
   ▼
POST <LANGFUSE_BASE_URL>/api/public/otel/v1/traces
   ▼
Langfuse UI:  trace tree, inputs/outputs, latency, tokens
```

The two changes compared with Example 2:

1. `CallbackHandler()` is passed to the agent in `config={"callbacks": [...]}`.
   LangChain calls it at every graph node, model call and tool call.
2. `get_client().flush()` runs before the program exits so nothing is lost.

## Step 1: get a Langfuse (free)

Pick **one** option.

**Option A: Langfuse Cloud (easiest, free Hobby plan)**

1. Sign up at [https://cloud.langfuse.com](https://cloud.langfuse.com) and create a project.
2. In the project: **Settings -> API Keys -> Create new API keys**. Copy the public (`pk-lf-...`) and secret (`sk-lf-...`) keys.
3. Use `LANGFUSE_BASE_URL=https://cloud.langfuse.com` (use the URL of your region if the UI shows a different one).

**Option B: self-hosted on your laptop (needs Docker)**

```bash
git clone https://github.com/langfuse/langfuse.git
cd langfuse && docker compose up
```

Open [http://localhost:3000](http://localhost:3000), create an account and a project, and copy the keys.
Use `LANGFUSE_BASE_URL=http://localhost:3000`.

## Step 2: add your keys

From the repository root, with the virtual environment active and the requirements
installed (`uv pip install -r requirements.txt`):

```bash
cd tutorial/example3_langfuse
cp .env.example .env          # then edit .env and paste your keys and URL
set -a; source .env; set +a   # load them into this terminal
```

`.env` is git-ignored, so your secret key is not committed.

## Step 3: run the agent

Without Ollama (scripted stand-in model):

```bash
FAKE_LLM=1 python agent.py
```

With Ollama:

```bash
python agent.py "Do you have a Python book in stock, and how much is it?"
```

Expected answer: `Book b1 costs $39.99 and there are 4 copies in stock.`

Notes:

- Without keys the agent still runs, but nothing is sent. You will see a
  "Langfuse client ... will be disabled" message.
- With `FAKE_LLM=1`, Langfuse prints "was not able to parse the LLM model". That
  is expected: the fake model has no real model name. With Ollama you get real
  model names and token counts.
- The "Processing request of type ..." lines come from the MCP server's logging.

## Step 4: look at it in Langfuse

Open the Langfuse UI -> your project -> **Tracing**. Open the `bookshop-agent` trace:

- The tree: LangGraph -> agent -> model call -> tools -> tool call.
- Input and output of every model call and tool call, plus latency per step.
- Token counts (with Ollama).

**Notice what is missing:** the MCP messages themselves (`initialize`,
`tools/list`, the raw JSON-RPC). Langfuse only sees what happens inside the agent.
That gap is what the proxy fills in Example 5.

## Try this

- Ask about a book that doesn't exist and compare the tool output with the model's answer.
- Find the slowest step in the trace and compare it with the others.
- Run the agent twice and compare the two traces in the list view.
