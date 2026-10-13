# Recording closed apps (Claude Desktop, Cursor, MCP Inspector)

Apps you can't change still talk to MCP servers. Point them at the AgentTrace
proxy instead of the real server and every request is recorded, with arguments and
results, and **no code changes**.

What you get: each request becomes its own trace (the app never sends a trace id),
grouped by **session** (one session per proxy process):

```bash
agenttrace sessions                     # one row per proxy process
agenttrace traces --session <id>        # everything one session did
```

You will see every MCP call, but not the app's own model conversation: that never
leaves the app.

## 1. Start AgentTrace first

```bash
source .venv/bin/activate
agenttrace up                           # http://127.0.0.1:7318
```

If AgentTrace isn't running, the app still works (the proxy just can't store spans).

## 2. Find the absolute paths

Desktop apps don't see your shell's `PATH` or virtual environment, so use absolute paths:

```bash
cd /path/to/AgentTrace
echo "$(pwd)/.venv/bin/agenttrace"                  # the proxy command
echo "$(pwd)/.venv/bin/python"                      # python of the venv
echo "$(pwd)/examples/bookshop/bookshop_server.py"  # the demo server
```

## 3. Claude Desktop (`claude_desktop_config.json`) / Cursor (`~/.cursor/mcp.json`)

Same format in both. Replace `/Users/you/AgentTrace` with your path:

```json
{
  "mcpServers": {
    "bookshop": {
      "command": "/Users/you/AgentTrace/.venv/bin/agenttrace",
      "args": ["proxy", "--name", "bookshop", "--",
               "/Users/you/AgentTrace/.venv/bin/python",
               "/Users/you/AgentTrace/examples/bookshop/bookshop_server.py"]
    },
    "filesystem": {
      "command": "/Users/you/AgentTrace/.venv/bin/agenttrace",
      "args": ["proxy", "--name", "filesystem", "--",
               "npx", "-y", "@modelcontextprotocol/server-filesystem", "/Users/you/Documents"]
    }
  }
}
```

The pattern is always `agenttrace proxy --name <label> -- <the real server command>`.
Restart the app after editing the file. If `npx` isn't found, use its absolute path
(`which npx`).

## 4. MCP Inspector

```bash
npx @modelcontextprotocol/inspector
```

In its connection form choose transport **STDIO**, command = the `agenttrace`
absolute path, arguments = `proxy --name bookshop -- /abs/path/python /abs/path/bookshop_server.py`.

## 5. Remote servers (Streamable HTTP)

For servers reachable by URL, run the HTTP proxy and give the app the proxy URL:

```bash
agenttrace proxy-http --name github --url https://example.com/mcp
# the app now uses  http://127.0.0.1:7319/mcp/github
```

The `Authorization` header is forwarded to the real server but never recorded.

## Check that it works

```bash
agenttrace sessions
agenttrace traces
agenttrace show <trace id>
agenttrace drift            # did any server change its tool descriptions?
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| App says the server failed to start | Run the exact command in a terminal; check the absolute paths |
| Nothing shows up in `agenttrace traces` | Is `agenttrace up` running? Do both use the same `AGENTTRACE_DB`? Check the proxy's stderr (`agenttrace proxy: recording ...`) |
| Using a non-default port | Set `AGENTTRACE_ENDPOINT=http://127.0.0.1:PORT` in the app's `env` block |
