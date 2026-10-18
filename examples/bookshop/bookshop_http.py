"""bookshop_http.py - the same Bookshop MCP server, but reachable over HTTP (Streamable HTTP).

The stdio version (bookshop_server.py) is started by the agent. This one is a long-running web
server, which is what an API gateway such as WSO2 API Manager can sit in front of:

    python bookshop_http.py                  # MCP endpoint: http://127.0.0.1:9100/mcp
    python bookshop_http.py --port 9200

It re-uses the tools of bookshop_server.py, so both versions always behave the same.
"""
# argparse reads --host/--port from the command line.
import argparse

# Reuse the same tools as the stdio version.
from bookshop_server import mcp
from mcp.server.transport_security import TransportSecuritySettings

# config.yaml: the default port.
from agenttrace import config

# Describe the options.
parser = argparse.ArgumentParser(description="Bookshop MCP server over Streamable HTTP")
# Which address to listen on.
parser.add_argument("--host", default="127.0.0.1")
# Which port to listen on.
parser.add_argument("--port", type=int, default=config.bookshop_http_port())  # config.yaml: bookshop.http_port
# Read what the user typed.
args = parser.parse_args()

# Tell FastMCP where to listen.
mcp.settings.host = args.host  # FastMCP reads these when it starts the web server
# And on which port.
mcp.settings.port = args.port
# FastMCP rejects requests whose Host header is not listed (protection against DNS rebinding). A gateway running in
# Docker calls us as host.docker.internal, so allow that name as well as localhost.
mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[host for name in ("127.0.0.1", "localhost", "host.docker.internal")
                   for host in (name, f"{name}:{args.port}")])  # with and without the port: the gateway omits it
# Start the web server (blocks until Ctrl+C).
mcp.run(transport="streamable-http")  # serves POST /mcp (path from mcp.settings.streamable_http_path)
