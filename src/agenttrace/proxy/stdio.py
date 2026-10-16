"""The stdio MCP proxy: client <-> proxy <-> real server. Every request becomes a span.

MCP over stdio is one JSON-RPC message per line. The proxy:
  1. starts the real server as a child process,
  2. copies lines client -> server and server -> client (two tasks running at once),
  3. passes each parsed line through the Recorder, which creates the spans.

      client ──stdin──► [pump + recorder.on_request ] ──stdin──► real server
      client ◄─stdout── [pump + recorder.on_response] ◄─stdout── real server

stdout belongs to the protocol: this file must NEVER print() to it (use stderr).
"""
import asyncio
import json
import sys

from agenttrace import config
from agenttrace.proxy.recorder import Recorder
from agenttrace.proxy.sessions import Session, make_provider

BUFFER = 16 * 1024 * 1024  # biggest single line accepted (16 MB): large tool results fit


def log(text: str) -> None:
    print(f"agenttrace proxy: {text}", file=sys.stderr, flush=True)


class StdioProxy:
    def __init__(self, command: list[str], server_name: str):
        self.command = command
        self.session = Session(server_name=server_name, command=command)
        self.provider = make_provider(self.session)
        self.recorder = Recorder(self.provider.get_tracer("agenttrace.proxy"), server_name)

    async def pump(self, reader, write, handler):
        """Copy lines from reader to write(), letting `handler` record each message.

        Recording must never break the connection: if anything goes wrong, the
        original line is forwarded untouched.
        """
        while line := await reader.readline():  # b"" means the other side closed
            try:
                msg = json.loads(line)
                line = (json.dumps(handler(msg), ensure_ascii=False) + "\n").encode()
            except json.JSONDecodeError:
                pass  # not JSON: forward as is
            except Exception as err:  # a bug in the recorder must not kill the MCP session
                log(f"could not record a message ({err!r}); forwarded unchanged")
            await write(line)

    async def run(self) -> int:
        loop = asyncio.get_running_loop()
        log(f"recording '{self.session.server_name}' (session {self.session.session_id[:8]}) -> {config.ENDPOINT}")
        # Start the REAL server as a child process; its stderr goes straight to ours.
        server = await asyncio.create_subprocess_exec(
            *self.command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, limit=BUFFER)
        # Our own stdin is where the client talks to us; wrap it in an async reader.
        stdin = asyncio.StreamReader(limit=BUFFER)
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(stdin), sys.stdin)

        async def to_server(data: bytes):
            server.stdin.write(data)
            await server.stdin.drain()

        async def to_client(data: bytes):
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()

        tasks = [asyncio.create_task(self.pump(stdin, to_server, self.recorder.on_request)),
                 asyncio.create_task(self.pump(server.stdout, to_client, self.recorder.on_response))]
        # Stop when EITHER side closes: the client hung up, or the server exited.
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in tasks:
            t.cancel()
        if server.returncode is None:
            server.terminate()
        self.recorder.close_pending()  # requests that never got an answer
        self.provider.shutdown()  # send the last batch of spans before exiting
        return server.returncode or 0
