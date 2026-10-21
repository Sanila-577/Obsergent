# Using Obsergent with the WSO2 API Platform MCP gateway

![Agent or app, Obsergent proxy, WSO2 gateway and MCP server in a row; the proxy and the gateway both send spans to the Obsergent server](diagrams/wso2-flow.png)

The gateway is the **WSO2 API Platform** gateway (github.com/wso2/api-platform, its `gateway` folder): a controller plus an Envoy
router, started with `docker compose`. It has no `bin/` start script (that was the old Java API Manager zip).

Commands marked **[gateway repo]** are typed inside the WSO2 repository; the others are run from this repository
(`make help` lists them; they use the Python environment that is active, or `.venv`). The ports, addresses, the MCP
server's name and path and the database file are in [config.yaml](../config.yaml) (`gateway:`, `server:`, `proxy:`,
`bookshop:` sections); `make config` prints what is in use.

## 1. Get the gateway and set it up (first time only)

```bash
git clone https://github.com/wso2/api-platform.git
cd api-platform/gateway                  # [gateway repo]
./scripts/setup.sh                       # [gateway repo] certificates, key, admin password: printed ONCE, copy it
```

Then let it send its traces to Obsergent: append this to `configs/config.toml` [gateway repo]:

```toml
[tracing]
enabled = true
endpoint = "host.docker.internal:4317"   # Obsergent's gRPC receiver, seen from inside Docker
insecure = true
service_version = "1.0.0"
batch_timeout = "1s"
max_export_batch_size = 512
sampling_rate = 1.0
```

## 2. Start everything, in this order

```bash
docker compose up                        # [gateway repo] controller REST :9090, router :8080 (-d runs it in the background)
```

**Run the next commands in the Obsergent repository** (this one), not in the WSO2 repository:

```bash
export WSO2AP_GW_PASSWORD='<the password setup.sh printed>'   # once per terminal; used to register the MCP server in the gateway
make start                                                   # everything below, detached: you keep the same terminal
make status                                                   # what is running;  make logs  follows the output
```

`make start` = `make up-grpc-bg` (Obsergent + UI + gRPC receiver), `make mcp-http-bg` (the MCP server the gateway protects),
`make register` (registers it in the gateway), `make proxy-bg` (Obsergent's recording proxy). They run detached with logs in
`.run/`; `make stop` stops them. Without the `-bg` suffix (`make up-grpc`, `make mcp-http`, `make proxy`) they run in the foreground.

What they do:

| Command                                                  | Detail                                                                                                                                                                                                                       |
| -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docker compose up`                                    | Starts the controller and the Envoy router from the published 1.2.1 images (building them yourself needs Go 1.25+ and is not required). The gateway has no UI of its own.                                                    |
| `make up-grpc-bg` (`make up-grpc` in the foreground) | stops anything already listening on `server.port` / `server.grpc_port` (such as an earlier `make up`), then starts the server with its gRPC receiver; the gateway's `[tracing] endpoint` must point at `server.grpc_port` |
| `make mcp-http-bg`                                     | `examples/bookshop/bookshop_http.py --host 0.0.0.0`; inside Docker the gateway reaches it as `http://host.docker.internal:9100/mcp`                                                                                      |
| `make register`                                        | One `POST <gateway.controller>/mcp-proxies` (default `http://localhost:9090/api/management/v1`) with a `kind: Mcp` body (same shape as `gateway/examples/mcp-proxy.yaml`); running it again updates the proxy        |
| `make proxy-bg`                                        | the HTTP recording proxy (name, URL and port from `config.yaml`: name `wso2`, URL `http://localhost:8080/bookshop/mcp`); clients use `http://127.0.0.1:7319/mcp/wso2`                                     |

The gateway forwards to **exactly** the upstream URL it was given, so that URL must end in `/mcp` (`make register` does
this). `make register-deny` adds the `mcp-acl-list` policy (only `search_books` allowed). Other policies (`mcp-auth`,
`mcp-authz`, `mcp-ratelimit`) go in the `policies:` section of the body; see the commented example in the platform's
`gateway/examples/mcp-proxy.yaml`. `mcp-auth` needs an identity provider; skip it at first. The proxy keeps the
`Authorization` header out of storage and the `Mcp-Session-Id` only as a fingerprint.

## 3. Send traffic

Your agent, with a question you type (the model comes from `.env`, see the README):

```bash
cd examples/bookshop
MCP_URL=http://127.0.0.1:7319/mcp/wso2 python agent.py "Do you have a Python book in stock, and how much is it?"
```

or plain test calls without a model: `make traffic` (through the proxy, so they are recorded).

## 4. Look at it

Open **http://127.0.0.1:7318**: **Conversations** shows each question (its **Timeline** tab: agent → LangGraph → tool step → proxy →
gateway `ingress` → policy engine / backend, all in one trace), **Gateway guard** shows the decisions (allowed, unauthorized,
forbidden, throttled, denied) and where the gateway spent its time. `make traces` lists runs in the terminal;
`docker compose logs -f gateway-runtime` [gateway repo] follows the gateway.

## 5. Stop everything and start again from scratch

```bash
make stop                                # stops what make start started
docker compose down                      # [gateway repo] `down -v` would also forget the registered MCP proxy (then `make register`)
make reset-db                            # EMPTIES Obsergent's database; Obsergent must be stopped first
```

## Troubleshooting

| Symptom                                                | Fix                                                                                                                                                                                 |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `register` says set WSO2AP_GW_PASSWORD               | Use the admin password `setup.sh` printed; rerun `setup.sh --force` to make a new one                                                                                            |
| `register` gets 401                                  | Wrong username or password (`gateway.username` in `config.yaml`, default `admin`)                                                                                             |
| Calls return 404 from the gateway                      | The upstream URL must include `/mcp` (the gateway sends requests to exactly that URL): `python scripts/wso2_gateway.py register --upstream http://host.docker.internal:9100/mcp` |
| 421 "Invalid Host header"                              | The MCP server only accepts listed Host names. `bookshop_http.py` already allows `host.docker.internal`; other servers need it added                                             |
| A tool the policy denies is missing from `tools/list` | Expected: the gateway filters the tool list too, so agents never see it and **Things to check** shows `tool_removed`                                                                 |
| Gateway cannot reach the server                        | On Linux add the host gateway or use the machine IP instead of `host.docker.internal`                                                                                              |
| No gateway spans in the UI                             | `make up-grpc` running? `[tracing] enabled = true` and the container restarted? Port 4317 free?                                                                                 |
| `could not listen on ... 4317`                       | Another collector uses it: stop it, or change `server.grpc_port` in `config.yaml` and `endpoint` in the gateway's `config.toml`                                             |
