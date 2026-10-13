"""The storage interfaces. SQLite implements them now; ClickHouse + PostgreSQL later.

Everything else in AgentTrace talks to these interfaces only, so swapping the
database never touches the API, the proxy or the analysis code.

Two interfaces, because later (server mode) they may live in different databases:
  * Storage   - the spans themselves (big, append-only, queried by trace)
  * MetaStore - small facts about them: sessions and tool snapshots
"""
from typing import Protocol

from agenttrace.models import Span


class Storage(Protocol):
    def save_spans(self, spans: list[Span]) -> None:
        """Insert (or overwrite, same span_id) a batch of spans."""

    def list_traces(self, limit: int = 50, service: str | None = None,
                    session_id: str | None = None) -> list[dict]:
        """One summary row per trace, newest first (duration, span count, tool calls, errors...)."""

    def get_trace(self, trace_id: str) -> list[Span]:
        """Every span of one trace, ordered by start time."""

    def resolve_trace_id(self, prefix: str) -> str | None:
        """Turn a short id prefix (as printed by the CLI) into the full trace id."""


class MetaStore(Protocol):
    def list_sessions(self, limit: int = 50) -> list[dict]:
        """One row per proxy session (a proxy process), newest first."""

    def save_tool_snapshot(self, server_name: str, tools: list[dict], seen_ns: int) -> bool:
        """Remember a tools/list result. Returns True if it differs from every earlier snapshot."""

    def list_tool_snapshots(self, server_name: str) -> list[dict]:
        """Snapshots of one server, oldest first: {id, fingerprint, first_seen_ns, tools}."""

    def list_servers(self) -> list[dict]:
        """Every MCP server we have snapshots for, with how many versions of its tool list."""
