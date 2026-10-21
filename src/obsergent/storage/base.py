"""The storage interfaces. SQLite implements them now; ClickHouse + PostgreSQL later.

Everything else in Obsergent talks to these interfaces only, so swapping the
database never touches the API, the proxy or the analysis code.

Two interfaces, because later (server mode) they may live in different databases:
  * Storage   - the spans themselves (big, append-only, queried by trace)
  * MetaStore - small facts about them: sessions and tool snapshots

A `Protocol` is a list of method names and signatures ("anything that has these methods counts"). It contains no
logic: it only documents what a database must be able to do. The real code is in storage/sqlite.py.
"""
# Protocol is the "list of required methods" base class.
from typing import Protocol

# The one data shape (see models.py) that every method below accepts or returns.
from obsergent.models import Span


# Everything about spans: saving them and querying them in different ways.
class Storage(Protocol):
    # Store a batch of spans; a span with an id that already exists is overwritten.
    def save_spans(self, spans: list[Span]) -> None:
        """Insert (or overwrite, same span_id) a batch of spans."""

    # The list of runs (traces) with a summary row each; all the arguments are optional filters.
    def list_traces(self, limit: int = 50, service: str | None = None, session_id: str | None = None,
                    model: str | None = None, errors_only: bool = False, tool: str | None = None,
                    server: str | None = None, query: str | None = None, decision: str | None = None,
                    since_ns: int | None = None, until_ns: int | None = None,
                    before_ns: int | None = None, with_models: bool = False) -> list[dict]:
        """One summary row per trace, newest first (duration, span count, tool calls, errors, models...).

        Every argument is an optional filter; `before_ns` pages backwards through older traces; `with_models` keeps
        only runs that contain a model call.
        """

    # Statistics per language model (how many calls, tokens, how slow).
    def list_model_usage(self) -> list[dict]:
        """Per model: calls, tokens and latency over every recorded model call."""

    # All the spans of one run.
    def get_trace(self, trace_id: str) -> list[Span]:
        """Every span of one trace, ordered by start time."""

    # The CLI shows only the first characters of an id; this finds the full id.
    def resolve_trace_id(self, prefix: str) -> str | None:
        """Turn a short id prefix (as printed by the CLI) into the full trace id."""

    # A general-purpose "find spans that have this attribute" query used by several dashboards.
    def find_spans(self, attribute: str | None = None, value: str | None = None, layer: str | None = None,
                   since_ns: int | None = None, limit: int = 5000) -> list[Span]:
        """Spans carrying an attribute (optionally with a given value), optionally of one layer, newest first."""

    # Every MCP tool call, with the handful of facts the dashboards need.
    def list_calls(self, since_ns: int | None = None, limit: int = 5000) -> list[dict]:
        """Every recorded MCP tool call with server, tool, duration, status and gateway decision."""

    # Every model call, for the cost views.
    def list_llm_spans(self, since_ns: int | None = None, limit: int = 20000) -> list[Span]:
        """Spans that are model calls, newest first."""

    # Number of tool calls (and failures) per time slot, for the chart on the Overview page.
    def activity_series(self, since_ns: int, until_ns: int, buckets: int) -> list[dict]:
        """Tool calls and errors per time bucket."""

    # The big numbers at the top of the Overview page.
    def overview_counts(self, since_ns: int | None = None) -> dict:
        """Headline numbers: runs, spans, tool calls, errors, model calls, tokens."""

    # The requests of one proxy session, for the session timeline.
    def list_session_spans(self, session_id: str) -> list[Span]:
        """Every MCP request of one proxy session, oldest first."""


# Small facts about the spans: sessions, tool lists and dismissed findings.
class MetaStore(Protocol):
    # The list of proxy sessions.
    def list_sessions(self, limit: int = 50) -> list[dict]:
        """One row per proxy session (a proxy process), newest first."""

    # Remember a server's tool list; returns True only if this exact list was never seen before.
    def save_tool_snapshot(self, server_name: str, tools: list[dict], seen_ns: int) -> bool:
        """Remember a tools/list result. Returns True if it differs from every earlier snapshot."""

    # All the remembered tool lists of one server (used to detect changes over time).
    def list_tool_snapshots(self, server_name: str) -> list[dict]:
        """Snapshots of one server, oldest first: {id, fingerprint, first_seen_ns, tools}."""

    # Which MCP servers we have seen.
    def list_servers(self) -> list[dict]:
        """Every MCP server we have snapshots for, with how many versions of its tool list."""

    # The user pressed "Dismiss" on a finding in the UI.
    def acknowledge_finding(self, finding_id: str, note: str = "") -> None:
        """Remember that a finding was looked at and dismissed."""

    # The user pressed "Restore".
    def unacknowledge_finding(self, finding_id: str) -> None:
        """Bring a dismissed finding back."""

    # Which findings are currently dismissed.
    def list_acknowledged(self) -> dict[str, int]:
        """Dismissed finding ids and when they were dismissed."""

    # --- prices (what a model costs; see analysis/pricing.py and server/price_sync.py) ---
    def save_prices(self, source: str, rows: list[dict], now_ns: int) -> int:
        """Store the prices a source reported (only the ones that changed). Returns how many rows were added."""

    def price_rows(self, models: list[str]) -> list[dict]:
        """The whole price history of these model names, oldest first."""

    def all_current_prices(self) -> list[dict]:
        """The newest price of every (source, provider, model)."""

    def save_sync(self, source: str, etag: str, fetched_ns: int, checked_ns: int, models: int, error: str = "") -> None:
        """Remember when a price list was downloaded."""

    def list_sync(self) -> list[dict]:
        """When each price list was last downloaded / checked."""

    def price_changes(self, since_ns: int, limit: int = 30) -> list[dict]:
        """Prices that changed since a moment (old and new input/output), newest first."""


# One combined interface: a database object that can do both of the above. The server only needs this.
class Backend(Storage, MetaStore, Protocol):
    """Everything the server needs from a database: spans AND metadata.

    SQLiteStorage is one object that implements both, so callers take a single `Backend`.
    """

    # What the price lists know about each model.
    def save_model_info(self, rows: list[dict]) -> int:
        """Store [{provider, model, info}] (context window, abilities...)."""

    def model_info(self, models: list[str]) -> list[dict]:
        """The stored facts for these model names."""

    def data_version(self) -> str:
        """A text that changes whenever something new is stored (the UI reloads when it changes)."""
