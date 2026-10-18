# Recording Claude Desktop, Cursor and other apps you can't modify

Apps like Claude Desktop talk to MCP servers, but you can't add AgentTrace's SDK to them. Instead you change **one entry
in the app's config** so that it starts `agenttrace proxy` instead of the server. The proxy starts the real server itself
and records every request (tool, arguments, result, timing), with **no code changes**.

```
Claude Desktop  ──►  agenttrace proxy  ──►  your MCP server
                          │ spans
                          ▼
                 agenttrace up  (server + web UI)  →  SQLite
```

What you will see: every MCP call Claude made, grouped into a **session** (one session = one proxy process = one
Claude Desktop connection to that server). Each call is its own run, because Claude sends no trace id. You will **not** see
Claude's own conversation: that never leaves the app.

## Step by step (Claude Desktop on macOS)

### 1. Start AgentTrace first

```bash
cd /path/to/AgentTrace
source .venv/bin/activate          # skip if an environment is already active (create it once: uv venv, then uv pip install -e ".[dev,langchain,examples,grpc]")
make up                            # leave this terminal open: http://127.0.0.1:7318 (server.port in config.yaml)
```

> **Order matters.** The proxy sends what it records to `agenttrace up`. If the server is not running while you use
> Claude, the calls still work, but **nothing is recorded** (Claude Desktop's log then shows
> `Max retries exceeded ... 127.0.0.1:7318`). Start `agenttrace up`, then use Claude.

### 2. Edit Claude Desktop's config

Claude Desktop → **Settings → Developer → Edit Config** (the file is
`~/Library/Application Support/Claude/claude_desktop_config.json`). Add an `mcpServers` entry at the top level of the JSON.
Use **absolute paths**: the app does not see your shell's `PATH` or virtual environment. Replace the path prefix with yours:

```json
{
  "mcpServers": {
    "bookshop": {
      "command": "/Users/you/AgentTrace/.venv/bin/agenttrace",
      "args": [
        "proxy", "--name", "bookshop", "--",
        "/Users/you/AgentTrace/.venv/bin/python",
        "/Users/you/AgentTrace/examples/bookshop/bookshop_server.py"
      ]
    }
  }
}
```

The pattern is always: `command` = the `agenttrace` program, `args` = `proxy --name <a label> -- <the real server's
command and arguments>`. If the file already has other settings, keep them: `"mcpServers"` is just one more key, and
**mind the commas** (a missing comma makes the whole file invalid and the app ignores it).

To find your paths: `echo "$(pwd)/.venv/bin/agenttrace"` from the repository root.

A second, third... server is just another entry, e.g. the filesystem server (use the absolute path of `npx`: `which npx`):

```json
"filesystem": {
  "command": "/Users/you/AgentTrace/.venv/bin/agenttrace",
  "args": ["proxy", "--name", "filesystem", "--",
           "/usr/local/bin/npx", "-y", "@modelcontextprotocol/server-filesystem", "/Users/you/Documents"]
}
```

### 3. Restart Claude Desktop completely

**Quit it (⌘Q)**, not just the window, then open it again. Claude only reads the config at start-up. In Settings →
Developer you should now see `bookshop` listed as **running**.

### 4. Use a tool

Ask something that needs the server, for example: *"Search the bookshop for Python books and tell me the price of the
first one."* Approve the tool use if Claude asks.

### 5. Look at what was recorded

Open **http://127.0.0.1:7318**:

* **Sessions** → the newest one (server `bookshop`) → the **session timeline**: every request in order, with arguments and results.
* **Runs** → each call is a run; open one for its timeline, and use *Copy as curl* to repeat the call.
* **Servers & tools** → `bookshop`: how often each tool was used, and the version history of its tool list.
* **Findings** → anything suspicious (a tool whose description changed, risky tool names, injection-like text).

The same in the terminal: `agenttrace sessions`, `agenttrace traces`, `agenttrace show <id>`.

## If it does not work

| Symptom | What to check |
|---|---|
| `bookshop` is not listed, or shows an error in Settings → Developer | The config JSON must be valid (commas!). Run the exact `command` + `args` in a terminal: it should wait silently (it is waiting for a client). Fix any path error. |
| `bookshop` runs but nothing appears in AgentTrace | Was `agenttrace up` running **before** you used Claude (step 1)? Same database and port? The proxy reads the repository's `config.yaml` (`server.port`, `storage.path`); if you moved the repository or use another config, add `"env": {"AGENTTRACE_CONFIG": "/abs/path/config.yaml"}` (or `"AGENTTRACE_ENDPOINT": "http://127.0.0.1:PORT"`) to the entry. |
| It stopped working after you restarted `agenttrace up` | The proxy keeps running inside Claude Desktop, so recording resumes by itself; if the server was down during a call, that call was not recorded. |
| `bookshop` shows as disconnected | Something stopped the proxy process (for example `pkill -f agenttrace`). Quit and reopen Claude Desktop. |
| Claude says it cannot find the tool | Quit and reopen Claude Desktop after every config change. |

Claude Desktop's own log for the server is `~/Library/Logs/Claude/mcp-server-bookshop.log` (named after the config key);
the proxy's messages (`agenttrace proxy: recording 'bookshop' ...`) and any export errors appear there.

## Cursor and MCP Inspector

* **Cursor**: the same JSON in `~/.cursor/mcp.json`.
* **MCP Inspector** (`npx @modelcontextprotocol/inspector`): choose transport **STDIO**, command = the `agenttrace`
  absolute path, arguments = `proxy --name bookshop -- /abs/path/python /abs/path/bookshop_server.py`.

## Remote servers (Streamable HTTP) and gateways

For a server reachable by URL, run the HTTP proxy and give the app the proxy's URL instead:

```bash
agenttrace proxy-http --name github --url https://example.com/mcp
# the app now uses  http://127.0.0.1:7319/mcp/github      (the port is proxy.port in config.yaml; --port overrides it)
```

The `Authorization` header is forwarded to the real server but never recorded. For a WSO2 API Platform gateway see
[wso2-integration.md](wso2-integration.md). Whether a given app accepts a plain `http://127.0.0.1` MCP URL depends on the
app; stdio servers through `agenttrace proxy` work everywhere.
