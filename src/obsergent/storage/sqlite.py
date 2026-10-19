"""SQLite storage: one file, no server, safe for several writers (WAL mode).

Implements both Storage (spans) and MetaStore (sessions, tool snapshots).

Tables and views
  spans           one row per span (the only big table)
  traces  (view)  one row per trace, computed on the fly from spans
  sessions (view) one row per proxy session, computed from spans that carry the
                  resource attribute obsergent.session.id
  tool_snapshots  every distinct tools/list result seen per MCP server

Words used below
  SQL       the language used to talk to a database ("SELECT ... FROM ... WHERE ...").
  table     rows and columns, like a spreadsheet.   view: a saved SELECT that behaves like a table.
  index     a lookup list the database keeps so searches on a column are fast.
  json_extract(attributes, '$."a.b"')   reads the key "a.b" out of the JSON text stored in the `attributes` column.
  "?"       a placeholder in a query; the real value is passed separately, which prevents SQL-injection attacks.
"""
# hashlib makes fingerprints (hashes) of data.
import hashlib

# json converts Python dicts/lists to JSON text (for storing) and back.
import json

# sqlite3 is Python's built-in SQLite driver.
import sqlite3

# time.time_ns() gives the current time in nanoseconds.
import time

# Path represents file locations.
from pathlib import Path

# percentile() computes e.g. the 95th percentile of a list of durations.
from obsergent.analysis.modelnames import group_key
from obsergent.analysis.stats import percentile

# The one data shape every part shares.
from obsergent.models import Span
from obsergent.storage import legacy

# --- schema, versioned with PRAGMA user_version so old database files upgrade themselves ---
# SCHEMA_V1 creates the spans table, three indexes and the first version of the traces view.
SCHEMA_V1 = """
-- Create the table only if it does not exist yet, so running this twice is harmless.
CREATE TABLE IF NOT EXISTS spans (
    -- PRIMARY KEY: no two rows may share a span_id.
    span_id         TEXT PRIMARY KEY,
    -- Which run the span belongs to.
    trace_id        TEXT NOT NULL,
    -- The parent span (empty for the root).
    parent_span_id  TEXT,
    -- What happened.
    name            TEXT NOT NULL,
    -- INTERNAL / CLIENT / SERVER ...
    kind            TEXT NOT NULL,
    -- Which program produced it.
    service         TEXT NOT NULL,
    -- Start and end time in nanoseconds since 1970.
    start_ns        INTEGER NOT NULL,
    end_ns          INTEGER NOT NULL,
    -- UNSET / OK / ERROR, with a reason in status_message.
    status_code     TEXT NOT NULL DEFAULT 'UNSET',
    status_message  TEXT NOT NULL DEFAULT '',
    -- All the free-form details, stored as JSON text.
    attributes      TEXT NOT NULL DEFAULT '{}',   -- JSON
    -- Timestamped notes inside the span, also JSON text.
    events          TEXT NOT NULL DEFAULT '[]'    -- JSON
);
-- Indexes make "all spans of trace X" / "newest first" / "by service" fast.
CREATE INDEX IF NOT EXISTS idx_spans_trace   ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_start   ON spans(start_ns);
CREATE INDEX IF NOT EXISTS idx_spans_service ON spans(service);
-- One row per trace, computed on the fly (fast enough for local volumes).
CREATE VIEW IF NOT EXISTS traces AS
-- GROUP BY trace_id below folds all the spans of one run into one row; these columns summarize them.
SELECT trace_id,
       -- Earliest start and latest end of the run's spans.
       MIN(start_ns)                                   AS start_ns,
       MAX(end_ns)                                     AS end_ns,
       -- Total duration in milliseconds.
       (MAX(end_ns) - MIN(start_ns)) / 1e6             AS duration_ms,
       -- How many spans the run has.
       COUNT(*)                                        AS span_count,
       -- How many spans failed (the comparison gives 1 or 0 per span; SUM adds them up).
       SUM(status_code = 'ERROR')                      AS error_count,
       -- How many MCP tool calls the run made.
       SUM(json_extract(attributes, '$."mcp.method.name"') = 'tools/call') AS tool_calls,
       -- The distinct programs that contributed spans, as a comma-separated list.
       GROUP_CONCAT(DISTINCT service)                  AS services
FROM spans GROUP BY trace_id;
"""

# SCHEMA_V2 adds sessions and the tool-list history.
SCHEMA_V2 = """
-- One row per proxy process. Closed apps (Claude Desktop, Cursor) send no trace id,
-- so every request becomes its own trace; the session groups them again.
CREATE VIEW IF NOT EXISTS sessions AS
-- The proxy writes obsergent.session.id onto every span; grouping by it gives one row per proxy process.
SELECT json_extract(attributes, '$."obsergent.session.id"')      AS session_id,
       -- Name of the MCP server and the (secret-free) command that started it.
       MAX(json_extract(attributes, '$."mcp.server.name"'))       AS server_name,
       MAX(json_extract(attributes, '$."obsergent.session.command"')) AS command,
       -- When the session started and ended.
       MIN(start_ns)                                              AS start_ns,
       MAX(end_ns)                                                AS end_ns,
       -- Counts: all requests, distinct runs, tool calls, failures.
       COUNT(*)                                                   AS span_count,
       COUNT(DISTINCT trace_id)                                   AS trace_count,
       SUM(json_extract(attributes, '$."mcp.method.name"') = 'tools/call') AS tool_calls,
       SUM(status_code = 'ERROR')                                 AS error_count
FROM spans
-- Ignore spans that have no session id (for example the agent's own spans).
WHERE json_extract(attributes, '$."obsergent.session.id"') IS NOT NULL
GROUP BY session_id;
-- Every distinct tools/list result per MCP server (to catch "rug pulls").
CREATE TABLE IF NOT EXISTS tool_snapshots (
    -- A running number, assigned automatically.
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Which MCP server the tool list belongs to.
    server_name    TEXT NOT NULL,
    fingerprint    TEXT NOT NULL,        -- hash of the whole tool list
    -- When this exact tool list was first seen.
    first_seen_ns  INTEGER NOT NULL,
    tools          TEXT NOT NULL,        -- JSON list of tool definitions
    -- The same list can never be stored twice for one server.
    UNIQUE (server_name, fingerprint)
);
"""
# SCHEMA_V3 replaces the traces view with one that also summarizes the language-model calls.
SCHEMA_V3 = """
-- The traces view again, with the LLM columns the runs list needs (a view cannot be altered, so replace it).
DROP VIEW IF EXISTS traces;
CREATE VIEW traces AS
SELECT trace_id,
       MIN(start_ns)                                   AS start_ns,
       MAX(end_ns)                                     AS end_ns,
       (MAX(end_ns) - MIN(start_ns)) / 1e6             AS duration_ms,
       COUNT(*)                                        AS span_count,
       SUM(status_code = 'ERROR')                      AS error_count,
       SUM(json_extract(attributes, '$."mcp.method.name"') = 'tools/call') AS tool_calls,
       GROUP_CONCAT(DISTINCT service)                  AS services,
       -- agent-side (LLM) facts, written by the SDK's OpenInference instrumentors
       -- Number of model calls in the run.
       SUM(json_extract(attributes, '$."openinference.span.kind"') = 'LLM') AS llm_calls,
       -- Which model names were used, and how many tokens in total.
       GROUP_CONCAT(DISTINCT json_extract(attributes, '$."llm.model_name"')) AS models,
       SUM(json_extract(attributes, '$."llm.token_count.total"')) AS total_tokens,
       -- The user and chat session the SDK was told about (at.context(...)).
       MAX(json_extract(attributes, '$."user.id"'))    AS user_id,
       MAX(json_extract(attributes, '$."session.id"')) AS chat_session
FROM spans GROUP BY trace_id;
"""
# SCHEMA_V4 adds columns for filtering (servers, tools, gateway decisions), speed-up indexes and dismissed findings.
SCHEMA_V4 = """
-- The traces view once more, now also listing servers, tools and gateway decisions (for filtering the runs list).
DROP VIEW IF EXISTS traces;
CREATE VIEW traces AS
SELECT trace_id,
       MIN(start_ns)                                   AS start_ns,
       MAX(end_ns)                                     AS end_ns,
       (MAX(end_ns) - MIN(start_ns)) / 1e6             AS duration_ms,
       COUNT(*)                                        AS span_count,
       SUM(status_code = 'ERROR')                      AS error_count,
       SUM(json_extract(attributes, '$."mcp.method.name"') = 'tools/call') AS tool_calls,
       GROUP_CONCAT(DISTINCT service)                  AS services,
       SUM(json_extract(attributes, '$."openinference.span.kind"') = 'LLM') AS llm_calls,
       GROUP_CONCAT(DISTINCT json_extract(attributes, '$."llm.model_name"')) AS models,
       SUM(json_extract(attributes, '$."llm.token_count.total"')) AS total_tokens,
       MAX(json_extract(attributes, '$."user.id"'))    AS user_id,
       MAX(json_extract(attributes, '$."session.id"')) AS chat_session,
       -- The new columns: which MCP servers, which tools and which gateway decisions the run involved.
       GROUP_CONCAT(DISTINCT json_extract(attributes, '$."mcp.server.name"')) AS servers,
       GROUP_CONCAT(DISTINCT json_extract(attributes, '$."gen_ai.tool.name"')) AS tools,
       GROUP_CONCAT(DISTINCT json_extract(attributes, '$."gateway.decision"')) AS decisions
FROM spans GROUP BY trace_id;
-- Expression indexes: the UI filters and aggregates by these attributes all the time.
CREATE INDEX IF NOT EXISTS idx_spans_tool ON spans(json_extract(attributes, '$."gen_ai.tool.name"'));
CREATE INDEX IF NOT EXISTS idx_spans_server ON spans(json_extract(attributes, '$."mcp.server.name"'));
CREATE INDEX IF NOT EXISTS idx_spans_activity ON spans(json_extract(attributes, '$."gateway.activity_id"'));
CREATE INDEX IF NOT EXISTS idx_spans_session_hash ON spans(json_extract(attributes, '$."mcp.session.hash"'));
-- Findings the user has looked at and dismissed.
CREATE TABLE IF NOT EXISTS finding_acks (
    -- The finding's stable id (see analysis/findings.py).
    finding_id       TEXT PRIMARY KEY,
    -- When it was dismissed, and an optional note.
    acknowledged_ns  INTEGER NOT NULL,
    note             TEXT NOT NULL DEFAULT ''
);
"""
# SCHEMA_V5 adds the price lists (what a model costs) and a log of when each list was downloaded.
SCHEMA_V5 = """
-- One row per price a source reported for a model. A new row is added only when the price CHANGED, so the table is a
-- history: the price valid at a given moment is the newest row at or before that moment.
CREATE TABLE IF NOT EXISTS model_prices (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Who serves the model (openai, anthropic, groq, openrouter ...) and its name there.
    provider          TEXT NOT NULL,
    model             TEXT NOT NULL,
    -- Which public list the price came from: models_dev, openrouter, huggingface, litellm.
    source            TEXT NOT NULL,
    -- When Obsergent first saw this price.
    effective_from_ns INTEGER NOT NULL,
    -- Dollars per MILLION tokens; NULL = the list does not say.
    input             REAL,
    output            REAL,
    cache_read        REAL,
    cache_write       REAL,
    reasoning         REAL,
    -- Anything else the list knows (long-context tiers ...), as JSON.
    extra             TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_prices_model ON model_prices(model, effective_from_ns);
-- When each list was last downloaded, its ETag (so unchanged lists are not downloaded again) and what went wrong, if anything.
CREATE TABLE IF NOT EXISTS price_sync (
    source      TEXT PRIMARY KEY,
    etag        TEXT NOT NULL DEFAULT '',
    fetched_ns  INTEGER NOT NULL DEFAULT 0,
    checked_ns  INTEGER NOT NULL DEFAULT 0,
    models      INTEGER NOT NULL DEFAULT 0,
    error       TEXT NOT NULL DEFAULT ''
);
"""
# SCHEMA_V6 is the rename to Obsergent: the key prefix and the proxy's service name inside old spans change, and the two
# views that read those keys are rebuilt (SCHEMA_V2 creates `sessions` and `tool_snapshots`, SCHEMA_V4 `traces`;
# both are safe to run again).
SCHEMA_V6 = f"""
UPDATE spans SET attributes = replace(attributes, '{legacy.KEY_PREFIX}', '"obsergent.'),
                 service = CASE service WHEN '{legacy.SERVICE}' THEN 'obsergent-proxy' ELSE service END
WHERE attributes LIKE '%{legacy.KEY_PREFIX}%' OR service = '{legacy.SERVICE}';
DROP VIEW IF EXISTS sessions;
""" + SCHEMA_V2 + SCHEMA_V4
# SCHEMA_V7 keeps what the price lists know about each model (context window, abilities...) for the Models page.
SCHEMA_V7 = """
CREATE TABLE IF NOT EXISTS model_info (
    provider  TEXT NOT NULL,
    model     TEXT NOT NULL,
    -- The facts as JSON (name, family, context, output limit, modalities, tool calling, reasoning, open weights, dates).
    info      TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (provider, model)
);
"""
# The list of steps in order. A database file at version N has already had the first N of these applied.
MIGRATIONS = [SCHEMA_V1, SCHEMA_V2, SCHEMA_V3, SCHEMA_V4, SCHEMA_V5, SCHEMA_V6, SCHEMA_V7]  # index + 1 = schema version

# Attributes the generic span lookup is allowed to filter on (the name goes into a SQL JSON path, so no free text).
LOOKUP_ATTRIBUTES = {"gateway.activity_id", "gen_ai.tool.name", "mcp.server.name", "mcp.session.hash",
                     "obsergent.layer", "mcp.method.name", "gateway.phase", "gateway.decision"}


def fingerprint_tools(tools: list[dict]) -> str:
    """Short, stable hash of a tool list (order of tools and of keys does not matter)."""
    # Sort the tools by name so the same tools in a different order give the same fingerprint.
    ordered = sorted(tools, key=lambda t: t.get("name", ""))
    # json.dumps(sort_keys=True) writes the same text for the same data; sha256 turns it into a short unique-looking code;
    # [:16] keeps the first 16 characters.
    return hashlib.sha256(json.dumps(ordered, sort_keys=True).encode()).hexdigest()[:16]


class SQLiteStorage:
    """The database object. Every method opens its own short connection, which makes it safe to share."""

    def __init__(self, path: str | Path):
        # Remember the file location as a Path object.
        self.path = Path(path)
        # Create the folder if needed (parents=True makes missing parent folders; exist_ok=True: no error if it exists).
        self.path.parent.mkdir(parents=True, exist_ok=True)  # ~/.obsergent/ may not exist yet
        # First start after the rename: bring the old database along (default location only).
        legacy.copy_old_database(self.path)
        # Make sure the tables and views exist and are up to date.
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        """Open the database, making sure the tables exist.

        The file can disappear while the server runs (`make reset-db` deletes it). SQLite then quietly creates a new,
        EMPTY file with no tables, and every query would fail with "no such table" (an HTTP 500). So every connection
        checks the schema version and re-creates the tables when the file is new: the pages then simply show "no data yet".
        """
        # The folder may have been deleted too.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = self.open()
        # A new or emptied file reports version 0; an up-to-date one reports len(MIGRATIONS).
        if db.execute("PRAGMA user_version").fetchone()[0] < len(MIGRATIONS):
            self.upgrade(db)
        return db

    def open(self) -> sqlite3.Connection:
        # Open the database file; timeout=10 means "if another process is writing, wait up to 10 seconds".
        db = sqlite3.connect(self.path, timeout=10)  # wait up to 10 s if another process is writing
        # WAL mode lets readers and one writer work at the same time (the server, the proxies and the CLI share the file).
        db.execute("PRAGMA journal_mode=WAL")  # readers and one writer at the same time
        # Make each result row act like a dictionary (row["name"]) instead of a plain tuple.
        db.row_factory = sqlite3.Row  # rows behave like dicts
        # Hand the open connection to the caller.
        return db

    def upgrade(self, db: sqlite3.Connection) -> None:
        """Apply the schema steps this file has not had yet, one at a time."""
        # SQLite stores a small integer called user_version inside the file; a new file has 0.
        version = db.execute("PRAGMA user_version").fetchone()[0]
        # Run only the steps the file has not had yet; `start` makes `step` the schema version number.
        for step, script in enumerate(MIGRATIONS[version:], start=version + 1):
            # executescript runs a whole block of SQL statements.
            db.executescript(script)
            # Record the new version, so the step is never repeated.
            db.execute(f"PRAGMA user_version = {step}")
        db.commit()

    def migrate(self) -> None:
        """Bring the file up to the latest schema version (called once at start-up; connect() also guards every use)."""
        self.connect().close()

    # ------------------------------------------------------------------ Storage
    def save_spans(self, spans: list[Span]) -> None:
        # Turn each Span into a tuple whose order matches the table's columns.
        rows = [(s.span_id, s.trace_id, s.parent_span_id, s.name, s.kind, s.service,
                 s.start_ns, s.end_ns, s.status_code, s.status_message,
                 # Dicts and lists are stored as JSON text; default=str converts anything unusual (like a date) to text.
                 json.dumps(s.attributes, default=str), json.dumps(s.events, default=str))
                for s in spans]
        # Open a connection (committed when the block ends).
        with self.connect() as db:
            # OR REPLACE: the same span exported twice just overwrites itself.
            # executemany runs the INSERT once per row; the 12 question marks match the 12 columns.
            db.executemany("INSERT OR REPLACE INTO spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)

    def list_traces(self, limit: int = 50, service: str | None = None, session_id: str | None = None,
                    model: str | None = None, errors_only: bool = False, tool: str | None = None,
                    server: str | None = None, query: str | None = None, decision: str | None = None,
                    since_ns: int | None = None, until_ns: int | None = None,
                    before_ns: int | None = None, with_models: bool = False) -> list[dict]:
        """Trace summaries, newest first. Every argument is an optional filter; `before_ns` pages backwards;
        `with_models` keeps only runs that contain at least one model call (the questions someone asked)."""
        # `where` collects the conditions, `args` the matching values for the "?" placeholders.
        where, args = [], []

        # A small helper: add one condition and its values.
        def add(condition: str, *values) -> None:
            where.append(condition)
            args.extend(values)

        # Each `if` below adds a condition only when the caller supplied that filter.
        if service:
            # LIKE '%x%' means "contains x".
            add("services LIKE ?", f"%{service}%")
        if model:
            add("models LIKE ?", f"%{model}%")
        if tool:
            # Wrap the stored list in commas and look for ",tool," so "search" does not match "search_books".
            add("(',' || tools || ',') LIKE ?", f"%,{tool},%")  # whole tool names only
        if server:
            add("(',' || servers || ',') LIKE ?", f"%,{server},%")
        if decision:
            add("decisions LIKE ?", f"%{decision}%")
        if errors_only:
            add("error_count > 0")
        if with_models:
            add("llm_calls > 0")
        if session_id:
            # Runs that contain at least one span carrying this proxy-session id.
            add("trace_id IN (SELECT trace_id FROM spans "
                "WHERE json_extract(attributes, '$.\"obsergent.session.id\"') = ?)", session_id)
        if query:  # free text inside names, arguments and results
            # Runs where any span's name or attributes (arguments, results...) contain the text.
            add("trace_id IN (SELECT trace_id FROM spans WHERE name LIKE ? OR attributes LIKE ?)",
                f"%{query}%", f"%{query}%")
        if since_ns is not None:
            add("start_ns >= ?", since_ns)
        if until_ns is not None:
            add("start_ns <= ?", until_ns)
        if before_ns is not None:
            # Used for paging: "only runs older than the last one I already have".
            add("start_ns < ?", before_ns)
        # Build the final query: all runs, filtered by the conditions joined with AND, newest first, at most `limit` rows.
        sql = "SELECT * FROM traces" + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY start_ns DESC LIMIT ?"
        with self.connect() as db:
            # Run it and turn each row into a plain dict.
            traces = [dict(r) for r in db.execute(sql, [*args, limit])]
            for t in traces:  # name each trace after its root span
                # The root span is the one with no parent (or whose parent is not in this run); take the earliest.
                root = db.execute(
                    "SELECT name FROM spans WHERE trace_id=? AND (parent_span_id IS NULL OR parent_span_id "
                    "NOT IN (SELECT span_id FROM spans WHERE trace_id=?)) ORDER BY start_ns LIMIT 1",
                    (t["trace_id"], t["trace_id"])).fetchone()
                # Use its name as the run's title ("?" if somehow there is none).
                t["root_name"] = root["name"] if root else "?"
        return traces

    def get_trace(self, trace_id: str) -> list[Span]:
        # Fetch every span of the run, oldest first.
        with self.connect() as db:
            rows = db.execute("SELECT * FROM spans WHERE trace_id=? ORDER BY start_ns", (trace_id,)).fetchall()
        # Convert each database row back into a Span object.
        return [self.row_to_span(r) for r in rows]

    def list_model_usage(self) -> list[dict]:
        """Per model: calls, tokens and latency (average, 95th percentile, max) over all recorded model calls.

        The same model recorded under two names (`gpt-4o-mini` and `gpt-4o-mini-2024-07-18`) is ONE entry; the raw names
        are listed in `versions`."""
        with self.connect() as db:
            # The query: group all spans that name a model by that exact name, and compute per group: the provider, the
            # number of calls, the sums of prompt/completion/total tokens, and the average and maximum duration in ms.
            rows = db.execute(
                "SELECT json_extract(attributes, '$.\"llm.model_name\"') AS model, "
                "       MAX(json_extract(attributes, '$.\"llm.provider\"')) AS provider, "
                "       COUNT(*) AS calls, "
                "       SUM(json_extract(attributes, '$.\"llm.token_count.prompt\"')) AS prompt_tokens, "
                "       SUM(json_extract(attributes, '$.\"llm.token_count.completion\"')) AS completion_tokens, "
                "       SUM(json_extract(attributes, '$.\"llm.token_count.total\"')) AS total_tokens, "
                "       SUM(end_ns - start_ns) / 1e6 AS total_ms, MAX((end_ns - start_ns) / 1e6) AS max_ms "
                "FROM spans WHERE model IS NOT NULL GROUP BY model").fetchall()
            merged: dict[tuple, dict] = {}
            for row in rows:
                entry = merged.setdefault(group_key(row["model"], row["provider"]), {
                    "model": group_key(row["model"], row["provider"])[1], "provider": row["provider"], "calls": 0,
                    "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "total_ms": 0.0, "max_ms": 0.0,
                    "versions": [], "durations": []})
                entry["calls"] += row["calls"]
                for key in ("prompt_tokens", "completion_tokens", "total_tokens", "total_ms"):
                    entry[key] += row[key] or 0
                entry["max_ms"] = max(entry["max_ms"], row["max_ms"] or 0)
                entry["provider"] = entry["provider"] or row["provider"]
                entry["versions"].append(row["model"])
                # Fetch every duration of that raw name, to combine them for the 95th percentile.
                entry["durations"] += [r[0] for r in db.execute(
                    "SELECT (end_ns - start_ns) / 1e6 FROM spans "
                    "WHERE json_extract(attributes, '$.\"llm.model_name\"') = ?", (row["model"],))]
        usage = []
        for entry in merged.values():
            durations = sorted(entry.pop("durations"))
            entry["avg_ms"] = entry.pop("total_ms") / entry["calls"]
            # The 95th percentile: 95% of the calls were faster than this.
            entry["p95_ms"] = percentile(durations, 0.95)
            entry["versions"].sort()
            usage.append(entry)
        return sorted(usage, key=lambda entry: -entry["calls"])

    def resolve_trace_id(self, prefix: str) -> str | None:
        with self.connect() as db:
            # Find any span whose trace id starts with the typed prefix ("abc%" means "starts with abc").
            row = db.execute("SELECT trace_id FROM spans WHERE trace_id LIKE ? LIMIT 1",
                             (prefix + "%",)).fetchone()
        # Return the full id, or None if nothing matched.
        return row["trace_id"] if row else None

    def row_to_span(self, row: sqlite3.Row) -> Span:
        # Build a Span from a database row; the JSON text columns are parsed back into dict and list.
        return Span(trace_id=row["trace_id"], span_id=row["span_id"], parent_span_id=row["parent_span_id"],
                    name=row["name"], kind=row["kind"], service=row["service"], start_ns=row["start_ns"],
                    end_ns=row["end_ns"], status_code=row["status_code"], status_message=row["status_message"],
                    attributes=json.loads(row["attributes"]), events=json.loads(row["events"]))

    def find_spans(self, attribute: str | None = None, value: str | None = None, layer: str | None = None,
                   since_ns: int | None = None, limit: int = 5000) -> list[Span]:
        """Spans that carry `attribute` (optionally equal to `value`), newest first.

        `layer` = "gateway" for the API Manager spans, "agent" for everything else, None for both.
        """
        where, args = [], []
        if attribute:
            # The attribute name is pasted into the SQL text, so only names from a fixed allow-list are accepted.
            if attribute not in LOOKUP_ATTRIBUTES:
                raise ValueError(f"cannot filter on '{attribute}'")
            # The SQL expression that reads the attribute out of the JSON column.
            path = f"json_extract(attributes, '$.\"{attribute}\"')"
            # With a value: equal to it. Without one: "has the attribute at all".
            where.append(f"{path} = ?" if value is not None else f"{path} IS NOT NULL")
            if value is not None:
                args.append(value)
        if layer == "gateway":
            # Spans that ingest/gateway.py marked as coming from API Manager.
            where.append("json_extract(attributes, '$.\"obsergent.layer\"') = 'gateway'")
        elif layer == "agent":
            # Everything that is not marked as gateway.
            where.append("json_extract(attributes, '$.\"obsergent.layer\"') IS NULL")
        if since_ns is not None:
            where.append("start_ns >= ?")
            args.append(since_ns)
        # Assemble the query; WHERE is added only if there are conditions.
        sql = "SELECT * FROM spans" + (" WHERE " + " AND ".join(where) if where else "")
        with self.connect() as db:
            rows = db.execute(sql + " ORDER BY start_ns DESC LIMIT ?", [*args, limit]).fetchall()
        return [self.row_to_span(r) for r in rows]

    def list_llm_spans(self, since_ns: int | None = None, limit: int = 20000) -> list[Span]:
        """Every model call (spans that name a model or are marked LLM and are not MCP traffic), newest first."""
        sql = ("SELECT * FROM spans WHERE json_extract(attributes, '$.\"mcp.method.name\"') IS NULL AND "
               "(json_extract(attributes, '$.\"openinference.span.kind\"') = 'LLM' OR "
               "json_extract(attributes, '$.\"llm.model_name\"') IS NOT NULL)")
        args: list = []
        if since_ns is not None:
            sql += " AND start_ns >= ?"
            args.append(since_ns)
        with self.connect() as db:
            rows = db.execute(sql + " ORDER BY start_ns DESC LIMIT ?", [*args, limit]).fetchall()
        return [self.row_to_span(r) for r in rows]

    def list_calls(self, since_ns: int | None = None, limit: int = 5000) -> list[dict]:
        """Every recorded MCP tool call (proxy spans), newest first, with the facts the dashboards need."""
        # The query: take every span whose method is tools/call and pick out the server, tool, gateway decision and caller;
        # the last column looks up the service name of the run's root span (the "client" for the map page).
        sql = ("SELECT s.trace_id, s.span_id, s.start_ns, (s.end_ns - s.start_ns) / 1e6 AS duration_ms, s.status_code, "
               "  json_extract(s.attributes, '$.\"mcp.server.name\"') AS server, "
               "  json_extract(s.attributes, '$.\"gen_ai.tool.name\"') AS tool, "
               "  json_extract(s.attributes, '$.\"gateway.decision\"') AS decision, "
               "  json_extract(s.attributes, '$.\"obsergent.caller.client_id\"') AS client_id, "
               "  json_extract(s.attributes, '$.\"obsergent.caller.application\"') AS application, "
               "  (SELECT r.service FROM spans r WHERE r.trace_id = s.trace_id AND r.parent_span_id IS NULL "
               "   LIMIT 1) AS root_service "
               "FROM spans s WHERE json_extract(s.attributes, '$.\"mcp.method.name\"') = 'tools/call'")
        args: list = []
        if since_ns is not None:
            # Optionally restrict to a time window.
            sql += " AND s.start_ns >= ?"
            args.append(since_ns)
        with self.connect() as db:
            # Newest first, at most `limit` rows, each as a dict.
            return [dict(r) for r in db.execute(sql + " ORDER BY s.start_ns DESC LIMIT ?", [*args, limit])]

    def activity_series(self, since_ns: int, until_ns: int, buckets: int) -> list[dict]:
        """MCP tool calls and errors per time bucket between two instants (for the overview chart)."""
        # Each bucket spans this many nanoseconds (at least 1, to avoid dividing by zero).
        width = max(1, (until_ns - since_ns) // buckets)
        with self.connect() as db:
            # The query: for each tool-call span, compute which bucket it falls in ((start - since) / width, rounded
            # down), then count the calls and the failures per bucket.
            rows = db.execute(
                "SELECT CAST((start_ns - ?) / ? AS INTEGER) AS bucket, COUNT(*) AS calls, "
                "SUM(status_code = 'ERROR') AS errors FROM spans "
                "WHERE json_extract(attributes, '$.\"mcp.method.name\"') = 'tools/call' AND start_ns >= ? "
                "GROUP BY bucket", (since_ns, width, since_ns)).fetchall()
        # Index the result by bucket number for quick lookup.
        by_bucket = {r["bucket"]: r for r in rows}
        # Return one entry for EVERY bucket (zeros where nothing happened), so the chart has no gaps.
        return [{"start_ns": since_ns + i * width, "calls": by_bucket[i]["calls"] if i in by_bucket else 0,
                 "errors": (by_bucket[i]["errors"] or 0) if i in by_bucket else 0} for i in range(buckets)]

    def overview_counts(self, since_ns: int | None = None) -> dict:
        """Headline numbers: runs, spans, tool calls, errors, model calls, tokens."""
        # Either "only spans since X" or no restriction at all.
        args = [since_ns] if since_ns is not None else []
        where = "WHERE start_ns >= ?" if since_ns is not None else ""
        with self.connect() as db:
            # The query: one row of totals: distinct runs, spans, tool calls, failed spans, model calls, tokens.
            row = db.execute(
                "SELECT COUNT(DISTINCT trace_id) AS runs, COUNT(*) AS spans, "
                "SUM(json_extract(attributes, '$.\"mcp.method.name\"') = 'tools/call') AS tool_calls, "
                "SUM(status_code = 'ERROR') AS errors, "
                "SUM(json_extract(attributes, '$.\"openinference.span.kind\"') = 'LLM') AS llm_calls, "
                "SUM(json_extract(attributes, '$.\"llm.token_count.total\"')) AS tokens "
                f"FROM spans {where}", args).fetchone()
            # Questions: runs that contain at least one model call (see analysis/queries.py).
            questions = db.execute("SELECT COUNT(*) FROM traces WHERE llm_calls > 0"
                                   + (" AND start_ns >= ?" if since_ns is not None else ""), args).fetchone()[0]
        # SQL returns NULL for an empty sum; `or 0` turns that into 0.
        return {key: row[key] or 0 for key in row.keys()} | {"questions": questions}

    def list_session_spans(self, session_id: str) -> list[Span]:
        """Every MCP request recorded in one proxy session, oldest first (the session timeline)."""
        with self.connect() as db:
            # Spans of this session that are MCP requests (they carry mcp.method.name), in time order.
            rows = db.execute(
                "SELECT * FROM spans WHERE json_extract(attributes, '$.\"obsergent.session.id\"') = ? "
                "AND json_extract(attributes, '$.\"mcp.method.name\"') IS NOT NULL ORDER BY start_ns",
                (session_id,)).fetchall()
        return [self.row_to_span(r) for r in rows]

    # ---------------------------------------------------------------- MetaStore
    def acknowledge_finding(self, finding_id: str, note: str = "") -> None:
        with self.connect() as db:
            # Store "this finding was dismissed now" (REPLACE: dismissing twice just updates the row).
            db.execute("INSERT OR REPLACE INTO finding_acks VALUES (?, ?, ?)", (finding_id, time.time_ns(), note))

    def unacknowledge_finding(self, finding_id: str) -> None:
        with self.connect() as db:
            # Remove the dismissal.
            db.execute("DELETE FROM finding_acks WHERE finding_id = ?", (finding_id,))

    def list_acknowledged(self) -> dict[str, int]:
        """finding id -> when it was acknowledged."""
        with self.connect() as db:
            # A dict {finding_id: time_dismissed} built from every row.
            return {r["finding_id"]: r["acknowledged_ns"] for r in db.execute("SELECT * FROM finding_acks")}

    def list_sessions(self, limit: int = 50) -> list[dict]:
        with self.connect() as db:
            # Read the sessions view, newest first.
            return [dict(r) for r in db.execute(
                "SELECT * FROM sessions ORDER BY start_ns DESC LIMIT ?", (limit,))]

    def save_tool_snapshot(self, server_name: str, tools: list[dict], seen_ns: int) -> bool:
        with self.connect() as db:
            # INSERT OR IGNORE + UNIQUE(server_name, fingerprint): an unchanged tool list is a no-op.
            cur = db.execute(
                "INSERT OR IGNORE INTO tool_snapshots (server_name, fingerprint, first_seen_ns, tools) "
                "VALUES (?,?,?,?)",
                (server_name, fingerprint_tools(tools), seen_ns, json.dumps(tools, sort_keys=True)))
            # rowcount is 1 if a row was inserted (a new version), 0 if the list was already known.
            return cur.rowcount == 1  # 1 = a new version of the tool list

    def list_tool_snapshots(self, server_name: str) -> list[dict]:
        with self.connect() as db:
            # All remembered tool lists of one server, oldest first.
            rows = db.execute("SELECT * FROM tool_snapshots WHERE server_name=? ORDER BY first_seen_ns, id",
                              (server_name,)).fetchall()
        # Parse the stored JSON back into Python lists.
        return [{"id": r["id"], "fingerprint": r["fingerprint"], "first_seen_ns": r["first_seen_ns"],
                 "tools": json.loads(r["tools"])} for r in rows]

    def list_servers(self) -> list[dict]:
        with self.connect() as db:
            # One row per server: how many versions of its tool list exist, when first seen and when last changed.
            return [dict(r) for r in db.execute(
                "SELECT server_name, COUNT(*) AS versions, MIN(first_seen_ns) AS first_seen_ns, "
                "MAX(first_seen_ns) AS last_change_ns FROM tool_snapshots GROUP BY server_name "
                "ORDER BY server_name")]

    # ------------------------------------------------------------------ prices
    PRICE_FIELDS = ("input", "output", "cache_read", "cache_write", "reasoning")

    def save_prices(self, source: str, rows: list[dict], now_ns: int) -> int:
        """Store the prices a source reported; a row is added only when it differs from the newest one stored for the
        same (provider, model, source). Returns how many rows were added."""
        with self.connect() as db:
            # The newest stored price of every (provider, model) of this source.
            latest = {(r["provider"], r["model"]): r for r in db.execute(
                "SELECT p.* FROM model_prices p JOIN (SELECT provider, model, MAX(id) AS id FROM model_prices "
                "WHERE source = ? GROUP BY provider, model) m ON p.id = m.id", (source,))}
            added = 0
            for row in rows:
                old = latest.get((row["provider"], row["model"]))
                values = [row.get(field) for field in self.PRICE_FIELDS]
                extra = json.dumps(row.get("extra") or {}, sort_keys=True)
                # Unchanged price: nothing to store.
                if old and [old[field] for field in self.PRICE_FIELDS] == values and old["extra"] == extra:
                    continue
                db.execute("INSERT INTO model_prices (provider, model, source, effective_from_ns, input, output, "
                           "cache_read, cache_write, reasoning, extra) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (row["provider"], row["model"], source, now_ns, *values, extra))
                added += 1
            return added

    def price_rows(self, models: list[str]) -> list[dict]:
        """The whole price history of these model names (any provider and source), oldest first."""
        if not models:
            return []
        marks = ",".join("?" * len(models))
        with self.connect() as db:
            rows = db.execute(f"SELECT * FROM model_prices WHERE model IN ({marks}) ORDER BY effective_from_ns, id",
                              models).fetchall()
        return [dict(r) | {"extra": json.loads(r["extra"])} for r in rows]

    def all_current_prices(self) -> list[dict]:
        """The newest price of every (source, provider, model): used to compare the sources with each other."""
        with self.connect() as db:
            rows = db.execute("SELECT p.* FROM model_prices p JOIN (SELECT MAX(id) AS id FROM model_prices "
                              "GROUP BY source, provider, model) m ON p.id = m.id").fetchall()
        return [dict(r) | {"extra": json.loads(r["extra"])} for r in rows]

    def save_sync(self, source: str, etag: str, fetched_ns: int, checked_ns: int, models: int, error: str = "") -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO price_sync VALUES (?,?,?,?,?,?)",
                       (source, etag, fetched_ns, checked_ns, models, error))

    def list_sync(self) -> list[dict]:
        """When each price list was downloaded / checked, with how many models it holds."""
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM price_sync ORDER BY source")]

    def price_changes(self, since_ns: int, limit: int = 30) -> list[dict]:
        """Prices that CHANGED since `since_ns` (a new row after an earlier one for the same source and model), newest first."""
        sql = ("SELECT n.provider, n.model, n.source, n.effective_from_ns, n.input AS new_input, n.output AS new_output, "
               "o.input AS old_input, o.output AS old_output FROM model_prices n JOIN model_prices o ON o.id = "
               "(SELECT MAX(x.id) FROM model_prices x WHERE x.source = n.source AND x.provider = n.provider "
               "AND x.model = n.model AND x.id < n.id) WHERE n.effective_from_ns >= ? "
               "AND (n.input IS NOT o.input OR n.output IS NOT o.output) ORDER BY n.effective_from_ns DESC LIMIT ?")
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, (since_ns, limit))]

    # ------------------------------------------------------------- model info
    def save_model_info(self, rows: list[dict]) -> int:
        """Store what a list knows about each model (context window, abilities...). Returns how many rows were written."""
        with self.connect() as db:
            db.executemany("INSERT OR REPLACE INTO model_info VALUES (?,?,?)",
                           [(r["provider"], r["model"], json.dumps(r["info"], sort_keys=True)) for r in rows])
        return len(rows)

    def model_info(self, models: list[str]) -> list[dict]:
        """The facts stored for these model names (any provider): [{provider, model, info}]."""
        if not models:
            return []
        marks = ",".join("?" * len(models))
        with self.connect() as db:
            rows = db.execute(f"SELECT * FROM model_info WHERE model IN ({marks})", models).fetchall()
        return [{"provider": r["provider"], "model": r["model"], "info": json.loads(r["info"])} for r in rows]
