"""Pretend to be a closed MCP app (like Claude Desktop): talk to a server THROUGH the AgentTrace proxy.

    python scripts/raw_mcp_session.py                      # one session with the bookshop server
    python scripts/raw_mcp_session.py --name shifty --server examples/bookshop/bookshop_server.py

No trace id is sent (a closed app never sends one), so every request becomes its own trace,
grouped by the proxy session. Start `agenttrace up` first. Then run:
    agenttrace traces      agenttrace sessions
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

parser = argparse.ArgumentParser()
parser.add_argument("--name", default="bookshop", help="server name shown in traces and sessions")
parser.add_argument("--server", default=str(ROOT / "examples" / "bookshop" / "bookshop_server.py"),
                    help="path of the MCP server script to run behind the proxy")
args = parser.parse_args()

# Exactly what Claude Desktop would start: `agenttrace proxy --name X -- <real server command>`.
proc = subprocess.Popen(
    [sys.executable, "-m", "agenttrace.cli", "proxy", "--name", args.name, "--", sys.executable, args.server],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

messages = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "raw", "version": "0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},  # a notification: no answer comes back
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    # "api_key" is a secret-looking key: check that the stored arguments show *** instead of SECRET123.
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "search_books", "arguments": {"query": "python", "api_key": "SECRET123"}}},
]
for msg in messages:
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if "id" in msg:  # wait for the answer, like a real client
        reply = json.loads(proc.stdout.readline())
        print(f"id={reply['id']}: {json.dumps(reply['result'])[:90]}...")
proc.stdin.close()  # hang up: the proxy sends its spans and exits
proc.wait(timeout=20)
print("done. Now run:  agenttrace traces   |   agenttrace sessions")
