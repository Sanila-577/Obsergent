"""A tiny Streamable-HTTP MCP server for trying `obsergent proxy-http` without any real remote server.

    python scripts/fake_http_mcp.py              # listens on http://127.0.0.1:9000/mcp
    obsergent proxy-http --name demo --url http://127.0.0.1:9000/mcp
    curl -s -X POST http://127.0.0.1:7319/mcp/demo -H 'content-type: application/json' \
         -H 'accept: application/json, text/event-stream' \
         -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"echo","arguments":{"text":"hi"}}}'

Tool `echo` answers with plain JSON, tool `stream` answers as an SSE stream.
"""
import json

import uvicorn
from fastapi import FastAPI, Request, Response

app = FastAPI()
TOOLS = [{"name": "echo", "description": "Echo the text back", "inputSchema": {"type": "object"}},
         {"name": "stream", "description": "Answer as an SSE stream", "inputSchema": {"type": "object"}}]


@app.post("/mcp")
async def mcp(request: Request):
    msg = await request.json()
    if "id" not in msg:  # a notification: accepted, no body
        return Response(status_code=202)
    method, msg_id = msg["method"], msg["id"]
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "FakeHTTP", "version": "0"}}
        return Response(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}),
                        media_type="application/json", headers={"mcp-session-id": "demo-session"})
    if method == "tools/list":
        reply = {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    else:
        text = json.dumps(msg["params"].get("arguments", {}))
        reply = {"jsonrpc": "2.0", "id": msg_id, "result": {"content": [{"type": "text", "text": text}]}}
        if msg["params"]["name"] == "stream":  # same answer, delivered as Server-Sent Events
            return Response(f"event: message\ndata: {json.dumps(reply)}\n\n", media_type="text/event-stream")
    return Response(json.dumps(reply), media_type="application/json")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9000, log_level="warning")
