# Recording Claude Desktop, Cursor and other apps you can't modify

Apps like Claude Desktop talk to MCP servers, but you can't add Obsergent's SDK to them. Instead you change **one entry
in the app's config** so that it starts Obsergent's proxy instead of the server. The proxy starts the real server itself
and records every request (tool, arguments, result, timing), with **no code changes**.

![Claude Desktop starts the Obsergent proxy, which starts your MCP server and sends what it records to the Obsergent server, stored in SQLite](diagrams/closed-apps.png)

What you will see: every MCP call Claude made, grouped into a **session** (one session = one proxy process = one
Claude Desktop connection to that server). Each call is its own run, because Claude sends no trace id. You will **not** see
Claude's own conversation: that never leaves the app.

## Step by step (Claude Desktop on macOS)

### 1. Start Obsergent first

```bash
cd /path/to/Obsergent
make up                            # leave this terminal open: http://127.0.0.1:7318 (server.port in config.yaml)
```

(The environment comes from the README's [Prerequisites](../README.md#1-prerequisites); `make` finds `.venv` by itself.)

> **Order matters.** The proxy sends what it records to the Obsergent server. If the server is not running while you use
> Claude, the calls still work, but **nothing is recorded** (Claude Desktop's log then shows
> `Max retries exceeded ... 127.0.0.1:7318`). Run `make up` first, then use Claude.

### 2. Edit Claude Desktop's config

Claude Desktop → **Settings → Developer → Edit Config** (the file is
`~/Library/Application Support/Claude/claude_desktop_config.json`). Add an `mcpServers` entry at the top level of the JSON.
Use **absolute paths**: the app does not see your shell's `PATH` or virtual environment. Replace the path prefix with yours.
This is the one place where the `obsergent` program is named directly: Claude Desktop starts it itself (`make` is only for
you in a terminal).

```json
{
  "mcpServers": {
    "bookshop": {
      "command": "/Users/you/Obsergent/.venv/bin/obsergent",
      "args": [
        "proxy", "--name", "bookshop", "--",
        "/Users/you/Obsergent/.venv/bin/python",
        "/Users/you/Obsergent/examples/bookshop/bookshop_server.py"
      ]
    }
  }
}
```

**Optional:** this is only needed if you want Claude to use more than one server; the bookshop entry above is enough. Each
extra server is one more entry, e.g. the filesystem server (use the absolute path of `npx`: `which npx`):

```json
"filesystem": {
  "command": "/Users/you/Obsergent/.venv/bin/obsergent",
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

* **App activity** → the newest session (server `bookshop`): every request in order, with arguments and results.
* **All activity** (switch to **Detailed** at the top) → each call is a run; open one for its timeline, and use *Copy as curl*
  to repeat the call.
* **MCPs** → `bookshop`: its tools, how often each was used, and (tab **Changes**) the version history of its tool list.
* **Things to check** → anything suspicious (a tool whose description changed, risky tool names, injection-like text).

The same in the terminal, from the repository root:

```bash
make sessions                # one line per proxy session (what Claude Desktop did with each server)
make traces                  # the recorded runs, newest first
make show ID=<run id>        # one run as a tree (the first characters of an id from make traces are enough)
```

Claude Desktop's own log for the server is `~/Library/Logs/Claude/mcp-server-bookshop.log` (named after the config key);
the proxy's messages (`obsergent proxy: recording 'bookshop' ...`) and any export errors appear there.

## Cursor and MCP Inspector

* **Cursor**: the same JSON in `~/.cursor/mcp.json`.
* **MCP Inspector** (`npx @modelcontextprotocol/inspector`): choose transport **STDIO**, command = the `obsergent`
  absolute path, arguments = `proxy --name bookshop -- /abs/path/python /abs/path/bookshop_server.py`.
* **Remote servers (Streamable HTTP) and gateways**: for a server reachable by URL, run the HTTP proxy and give the app the
  proxy's URL instead:

  ```bash
  make proxy NAME=github URL=https://example.com/mcp
  # the app now uses  http://127.0.0.1:7319/mcp/github      (the port is proxy.port in config.yaml)
  ```

The `Authorization` header is forwarded to the real server but never recorded. For a WSO2 API Platform gateway see
[wso2-integration.md](wso2-integration.md). Whether a given app accepts a plain `http://127.0.0.1` MCP URL depends on the
app; stdio servers through the proxy (step 2) work everywhere.
