"""SQLite storage: one file, no server, safe for several writers (WAL mode).

Implements both Storage (spans) and MetaStore (sessions, tool snapshots).

Tables and views
  spans           one row per span (the only big table)
  traces  (view)  one row per trace, computed on the fly from spans
  sessions (view) one row per proxy session, computed from spans that carry the
                  resource attribute agenttrace.session.id
  tool_snapshots  every distinct tools/list result seen per MCP server
"""
import hashlib
import json
import sqlite3
from pathlib import Path

from agenttrace.models import Span

# Attribute names the proxy writes (see proxy/recorder.py and proxy/sessions.py).
SESSION_ATTR = "agenttrace.session.id"

# --- schema, versioned with PRAGMA user_version so old database files upgrade themselves ---
SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS spans (
    span_id         TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL,
    parent_span_id  TEXT,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    service         TEXT NOT NULL,
    start_ns        INTEGER NOT NULL,
    end_ns          INTEGER NOT NULL,
    status_code     TEXT NOT NULL DEFAULT 'UNSET',
    status_message  TEXT NOT NULL DEFAULT '',
    attributes      TEXT NOT NULL DEFAULT '{}',   -- JSON
    events          TEXT NOT NULL DEFAULT '[]'    -- JSON
);
-- Indexes make "all spans of trace X" / "newest first" / "by service" fast.
CREATE INDEX IF NOT EXISTS idx_spans_trace   ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_start   ON spans(start_ns);
CREATE INDEX IF NOT EXISTS idx_spans_service ON spans(service);
-- One row per trace, computed on the fly (fast enough for local volumes).
CREATE VIEW IF NOT EXISTS traces AS
SELECT trace_id,
       MIN(start_ns)                                   AS start_ns,
       MAX(end_ns)                                     AS end_ns,
       (MAX(end_ns) - MIN(start_ns)) / 1e6             AS duration_ms,
       COUNT(*)                                        AS span_count,
       SUM(status_code = 'ERROR')                      AS error_count,
       SUM(json_extract(attributes, '$."mcp.method.name"') = 'tools/call') AS tool_calls,
       GROUP_CONCAT(DISTINCT service)                  AS services
FROM spans GROUP BY trace_id;
"""

SCHEMA_V2 = """
-- One row per proxy process. Closed apps (Claude Desktop, Cursor) send no trace id,
-- so every request becomes its own trace; the session groups them again.
CREATE VIEW IF NOT EXISTS sessions AS
SELECT json_extract(attributes, '$."agenttrace.session.id"')      AS session_id,
       MAX(json_extract(attributes, '$."mcp.server.name"'))       AS server_name,
       MAX(json_extract(attributes, '$."agenttrace.session.command"')) AS command,
       MIN(start_ns)                                              AS start_ns,
       MAX(end_ns)                                                AS end_ns,
       COUNT(*)                                                   AS span_count,
       COUNT(DISTINCT trace_id)                                   AS trace_count,
       SUM(json_extract(attributes, '$."mcp.method.name"') = 'tools/call') AS tool_calls,
       SUM(status_code = 'ERROR')                                 AS error_count
FROM spans
WHERE json_extract(attributes, '$."agenttrace.session.id"') IS NOT NULL
GROUP BY session_id;
-- Every distinct tools/list result per MCP server (to catch "rug pulls").
CREATE TABLE IF NOT EXISTS tool_snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    server_name    TEXT NOT NULL,
    fingerprint    TEXT NOT NULL,        -- hash of the whole tool list
    first_seen_ns  INTEGER NOT NULL,
    tools          TEXT NOT NULL,        -- JSON list of tool definitions
    UNIQUE (server_name, fingerprint)
);
"""
MIGRATIONS = [SCHEMA_V1, SCHEMA_V2]  # index + 1 = schema version


def fingerprint_tools(tools: list[dict]) -> str:
    """Short, stable hash of a tool list (order of tools and of keys does not matter)."""
    ordered = sorted(tools, key=lambda t: t.get("name", ""))
    return hashlib.sha256(json.dumps(ordered, sort_keys=True).encode()).hexdigest()[:16]


class SQLiteStorage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)  # ~/.agenttrace/ may not exist yet
        self._migrate()

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)  # wait up to 10 s if another process is writing
        db.execute("PRAGMA journal_mode=WAL")  # readers and one writer at the same time
        db.row_factory = sqlite3.Row  # rows behave like dicts
        return db

    def _migrate(self) -> None:
        """Bring the file up to the latest schema version, one step at a time."""
        with self._db() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            for step, script in enumerate(MIGRATIONS[version:], start=version + 1):
                db.executescript(script)
                db.execute(f"PRAGMA user_version = {step}")

    # ------------------------------------------------------------------ Storage
    def save_spans(self, spans: list[Span]) -> None:
        rows = [(s.span_id, s.trace_id, s.parent_span_id, s.name, s.kind, s.service,
                 s.start_ns, s.end_ns, s.status_code, s.status_message,
                 json.dumps(s.attributes, default=str), json.dumps(s.events, default=str))
                for s in spans]
        with self._db() as db:
            # OR REPLACE: the same span exported twice just overwrites itself.
            db.executemany("INSERT OR REPLACE INTO spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)

    def list_traces(self, limit: int = 50, service: str | None = None,
                    session_id: str | None = None) -> list[dict]:
        sql, args, where = "SELECT * FROM traces", [], []
        if service:
            where.append("services LIKE ?")
            args.append(f"%{service}%")
        if session_id:
            where.append("trace_id IN (SELECT trace_id FROM spans "
                         "WHERE json_extract(attributes, '$.\"agenttrace.session.id\"') = ?)")
            args.append(session_id)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY start_ns DESC LIMIT ?"
        args.append(limit)
        with self._db() as db:
            traces = [dict(r) for r in db.execute(sql, args)]
            for t in traces:  # name each trace after its root span
                root = db.execute(
                    "SELECT name FROM spans WHERE trace_id=? AND (parent_span_id IS NULL OR parent_span_id "
                    "NOT IN (SELECT span_id FROM spans WHERE trace_id=?)) ORDER BY start_ns LIMIT 1",
                    (t["trace_id"], t["trace_id"])).fetchone()
                t["root_name"] = root["name"] if root else "?"
        return traces

    def get_trace(self, trace_id: str) -> list[Span]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM spans WHERE trace_id=? ORDER BY start_ns", (trace_id,)).fetchall()
        return [Span(trace_id=r["trace_id"], span_id=r["span_id"], parent_span_id=r["parent_span_id"],
                     name=r["name"], kind=r["kind"], service=r["service"], start_ns=r["start_ns"],
                     end_ns=r["end_ns"], status_code=r["status_code"], status_message=r["status_message"],
                     attributes=json.loads(r["attributes"]), events=json.loads(r["events"]))
                for r in rows]

    def resolve_trace_id(self, prefix: str) -> str | None:
        with self._db() as db:
            row = db.execute("SELECT trace_id FROM spans WHERE trace_id LIKE ? LIMIT 1",
                             (prefix + "%",)).fetchone()
        return row["trace_id"] if row else None

    # ---------------------------------------------------------------- MetaStore
    def list_sessions(self, limit: int = 50) -> list[dict]:
        with self._db() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM sessions ORDER BY start_ns DESC LIMIT ?", (limit,))]

    def save_tool_snapshot(self, server_name: str, tools: list[dict], seen_ns: int) -> bool:
        with self._db() as db:
            # INSERT OR IGNORE + UNIQUE(server_name, fingerprint): an unchanged tool list is a no-op.
            cur = db.execute(
                "INSERT OR IGNORE INTO tool_snapshots (server_name, fingerprint, first_seen_ns, tools) "
                "VALUES (?,?,?,?)",
                (server_name, fingerprint_tools(tools), seen_ns, json.dumps(tools, sort_keys=True)))
            return cur.rowcount == 1  # 1 = a new version of the tool list

    def list_tool_snapshots(self, server_name: str) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM tool_snapshots WHERE server_name=? ORDER BY first_seen_ns, id",
                              (server_name,)).fetchall()
        return [{"id": r["id"], "fingerprint": r["fingerprint"], "first_seen_ns": r["first_seen_ns"],
                 "tools": json.loads(r["tools"])} for r in rows]

    def list_servers(self) -> list[dict]:
        with self._db() as db:
            return [dict(r) for r in db.execute(
                "SELECT server_name, COUNT(*) AS versions, MIN(first_seen_ns) AS first_seen_ns, "
                "MAX(first_seen_ns) AS last_change_ns FROM tool_snapshots GROUP BY server_name "
                "ORDER BY server_name")]
