"""The stdio MCP proxy: client <-> proxy <-> real server. Every request becomes a span.

MCP over stdio is one JSON-RPC message per line. The proxy:
  1. starts the real server as a child process,
  2. copies lines client -> server and server -> client (two tasks running at once),
  3. passes each parsed line through the Recorder, which creates the spans.

      client ──stdin──► [pump + recorder.on_request ] ──stdin──► real server
      client ◄─stdout── [pump + recorder.on_response] ◄─stdout── real server

stdio = "standard input/output": every program has a text input pipe (stdin) and a text output pipe (stdout).
The MCP client launches the server as a child process and talks to it through these two pipes.

stdout belongs to the protocol: this file must NEVER print() to it (use stderr).
"""
# asyncio runs several things "at the same time" in one thread (here: two pumps).
import asyncio

# json parses each line.
import json

# sys gives access to stdin/stdout/stderr.
import sys

# config.endpoint() is shown in the startup log line.
from agenttrace import config

# Recorder turns messages into spans.
from agenttrace.proxy.recorder import Recorder

# Session = identity of this proxy process; make_provider creates the OpenTelemetry exporter.
from agenttrace.proxy.sessions import Session, make_provider

# Biggest single line accepted (16 MB): large tool results fit.
BUFFER = 16 * 1024 * 1024


def log(text: str) -> None:
    # stderr is safe: the MCP client only reads stdout. flush=True writes immediately.
    print(f"agenttrace proxy: {text}", file=sys.stderr, flush=True)


class StdioProxy:
    def __init__(self, command: list[str], server_name: str):
        # The command that starts the REAL server, e.g. ["python", "bookshop_server.py"].
        self.command = command
        # This proxy process's identity (a new session id).
        self.session = Session(server_name=server_name, command=command)
        # The exporter that sends spans to the AgentTrace server.
        self.provider = make_provider(self.session)
        # The recorder uses a tracer from that provider.
        self.recorder = Recorder(self.provider.get_tracer("agenttrace.proxy"), server_name)

    async def pump(self, reader, write, handler):
        """Copy lines from reader to write(), letting `handler` record each message.

        Recording must never break the connection: if anything goes wrong, the
        original line is forwarded untouched.
        """
        # Read one line at a time until the pipe closes; `:=` assigns and tests in one step.
        while line := await reader.readline():  # b"" means the other side closed
            try:
                # Parse the line as JSON-RPC.
                msg = json.loads(line)
                # Let the recorder look at (and possibly extend) it, then turn it back into one line.
                line = (json.dumps(handler(msg), ensure_ascii=False) + "\n").encode()
            except json.JSONDecodeError:
                pass  # not JSON: forward as is
            except Exception as err:  # a bug in the recorder must not kill the MCP session
                log(f"could not record a message ({err!r}); forwarded unchanged")
            # Send the line on to the other side.
            await write(line)

    async def run(self) -> int:
        # The running event loop (needed to wrap our stdin).
        loop = asyncio.get_running_loop()
        log(f"recording '{self.session.server_name}' (session {self.session.session_id[:8]}) -> {config.endpoint()}")
        # Start the REAL server as a child process; its stderr goes straight to ours.
        server = await asyncio.create_subprocess_exec(
            *self.command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, limit=BUFFER)
        # Our own stdin is where the client talks to us; wrap it in an async reader.
        stdin = asyncio.StreamReader(limit=BUFFER)
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(stdin), sys.stdin)

        async def to_server(data: bytes):
            # Write the line into the child's stdin and wait until it is flushed.
            server.stdin.write(data)
            await server.stdin.drain()

        async def to_client(data: bytes):
            # Write the line to OUR stdout, where the client reads it.
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()

        # Two pumps running together: requests go client->server, responses go server->client.
        tasks = [asyncio.create_task(self.pump(stdin, to_server, self.recorder.on_request)),
                 asyncio.create_task(self.pump(server.stdout, to_client, self.recorder.on_response))]
        # Stop when EITHER side closes: the client hung up, or the server exited.
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        # Stop the other pump too.
        for t in tasks:
            t.cancel()
        # If the server is still alive, ask it to stop.
        if server.returncode is None:
            server.terminate()
        self.recorder.close_pending()  # requests that never got an answer
        self.provider.shutdown()  # send the last batch of spans before exiting
        # Pass the server's exit code on (0 if none).
        return server.returncode or 0
