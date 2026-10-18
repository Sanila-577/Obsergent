"""Register the Bookshop MCP server in the WSO2 API Platform gateway, then send test traffic through it.

    python scripts/wso2_gateway.py register     # create the MCP proxy in the gateway (one REST call)
    python scripts/wso2_gateway.py traffic      # initialize -> tools/list -> tools/call, printing every reply

The gateway (api-platform/gateway) runs in Docker. Its controller has a REST API, so no UI is needed:
    POST http://localhost:9090/api/management/v1/mcp-proxies     (basic auth: admin + the password setup.sh printed)
After that the gateway serves the MCP server at  http://localhost:8080/<context>/mcp.

Set WSO2AP_GW_PASSWORD (and WSO2AP_GW_USERNAME if it is not "admin"). Written from the gateway's OpenAPI file and
examples; the exact MCP path is printed so you can see if it differs.
"""
# argparse reads the command and options typed after the script name.
import argparse

# json parses replies and builds request bodies.
# sys: exit with a message.
import sys

# httpx is the HTTP client.
import httpx

# config.yaml: the gateway's addresses, the MCP server's name and path, ports.
from agenttrace import config

# Name and version of the MCP proxy we create in the gateway (its path and the addresses come from config.yaml).
NAME, VERSION = "bookshop", "v1.0"


def credentials() -> tuple[str, str]:
    # The password is printed once by gateway/scripts/setup.sh; never hard-code it.
    password = config.gateway_password()
    if not password:
        sys.exit("set WSO2AP_GW_PASSWORD (the admin password printed by gateway/scripts/setup.sh)")
    return config.gateway_username(), password


def register(upstream: str, deny_price: bool = False) -> None:
    """Create the MCP proxy. The body has the same shape as gateway/examples/mcp-proxy.yaml."""
    body = {
        "apiVersion": "gateway.api-platform.wso2.com/v1",
        "kind": "Mcp",
        "metadata": {"name": f"{NAME}-{VERSION}"},
        "spec": {"displayName": "Bookshop", "version": VERSION, "context": config.mcp_context(), "specVersion": "2025-06-18",
                 "upstream": {"url": upstream}, "tools": [], "resources": [], "prompts": []},
    }
    if deny_price:
        # MCP Access Control policy: mode "deny" with exceptions = an allow-list. Only search_books gets through.
        body["spec"]["policies"] = [{"name": "mcp-acl-list", "version": "v1",
                                     "params": {"tools": {"mode": "deny", "exceptions": ["search_books"]}}}]
    reply = httpx.post(f"{config.gateway_controller()}/mcp-proxies", json=body, auth=credentials(), timeout=30)
    # 201 = created, 409 = same name and version already exists: update it in place (PUT) so re-running fixes settings.
    if reply.status_code == 409:
        reply = httpx.put(f"{config.gateway_controller()}/mcp-proxies/{NAME}-{VERSION}", json=body, auth=credentials(),
                          timeout=30)
        if reply.status_code != 200:
            sys.exit(f"gateway answered {reply.status_code}: {reply.text}")
        print("updated")
    elif reply.status_code != 201:
        sys.exit(f"gateway answered {reply.status_code}: {reply.text}")
    else:
        print("registered")
    print(f"MCP endpoint: {config.gateway_mcp_url()}")


def traffic(url: str, token: str | None) -> None:
    """Speak MCP over HTTP to `url`: initialize, initialized, tools/list, tools/call (twice)."""
    headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=30, verify=False) as client:
        def send(message: dict) -> None:
            reply = client.post(url, json=message, headers=headers)
            # The session id comes back on `initialize` and must be sent on every later request.
            if "mcp-session-id" in reply.headers:
                headers["mcp-session-id"] = reply.headers["mcp-session-id"]
            print(f"{message.get('method'):<28} HTTP {reply.status_code}  {reply.text[:150]!r}")

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "wso2-gateway-script", "version": "1"}}})
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        for call_id, query in ((3, "python"), (4, "data")):
            send({"jsonrpc": "2.0", "id": call_id, "method": "tools/call",
                  "params": {"name": "search_books", "arguments": {"query": query}}})
        # A second tool: with the `deny` access-control policy (register --deny-price) the gateway refuses this one.
        send({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
              "params": {"name": "get_price_and_stock", "arguments": {"book_id": "b1"}}})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    reg = sub.add_parser("register", help="create the MCP proxy in the gateway")
    reg.add_argument("--upstream", default=None,
                     help="real MCP server URL as seen FROM INSIDE Docker, sent to as is so it must end in /mcp "
                          "(default: host.docker.internal and bookshop.http_port from config.yaml)")
    reg.add_argument("--deny-price", action="store_true",
                     help="add the mcp-acl-list policy so only search_books is allowed (get_price_and_stock is refused)")
    run = sub.add_parser("traffic", help="send test MCP traffic")
    run.add_argument("--url", default=None, help="MCP URL (default: through the AgentTrace proxy, from config.yaml, "
                                                 "so the calls are recorded)")
    run.add_argument("--direct", action="store_true", help="call the gateway directly instead (not recorded)")
    run.add_argument("--token", default=None, help="bearer token, only if you enabled the mcp-auth policy")
    args = parser.parse_args()
    if args.cmd == "register":
        register(args.upstream or f"http://host.docker.internal:{config.bookshop_http_port()}/mcp", args.deny_price)
    else:
        traffic(args.url or (config.gateway_mcp_url() if args.direct else config.proxy_url()), args.token)


if __name__ == "__main__":
    main()
