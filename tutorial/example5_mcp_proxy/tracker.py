"""tracker.py - a tiny custom OpenTelemetry tracker.

OpenTelemetry lets you plug in your own *exporter*: the piece that receives
finished spans. This exporter saves every span into a SQLite database file,
which is exactly what Obsergent's local mode does at a bigger scale.

Vocabulary used below:
  trace  = the full story of one run (e.g. "making one cup of tea").
  span   = one step inside a trace (e.g. "boil_water"). It has a name, a start
           time, an end time, a status and key/value attributes.
  parent = a span can contain child spans, so a trace forms a tree.
"""
import json  # to store the attributes dictionary as text in one SQLite column
import os  # to read an environment variable (TRACKER_DB)
import sqlite3  # Python's built-in SQLite database driver
from typing import Sequence  # type hint: "a list-like collection of ..."

from opentelemetry import trace  # the public API used to create/get tracers
from opentelemetry.sdk.resources import Resource  # describes WHO produces the spans
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider  # SDK pieces: finished span + factory of tracers
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,  # sends each span to the exporter immediately when it ends
    SpanExporter,  # base class we extend to make our own exporter
    SpanExportResult,  # SUCCESS / FAILURE value our export() must return
)

# Which database file to write to. Uses the TRACKER_DB environment variable if
# it is set, otherwise a file called traces.db in the current folder.
DEFAULT_DB = os.environ.get("TRACKER_DB", "traces.db")

# The table layout: one row per span. Written in SQL, run once at startup.
SCHEMA = """
CREATE TABLE IF NOT EXISTS spans (
    trace_id    TEXT NOT NULL,        -- 32 hex chars; identical for every span of one run
    span_id     TEXT PRIMARY KEY,     -- 16 hex chars; unique per span
    parent_id   TEXT,                 -- span_id of the parent; NULL for the root span
    name        TEXT NOT NULL,        -- what the step is called, e.g. boil_water
    kind        TEXT,                 -- INTERNAL, CLIENT, SERVER... (what role the span plays)
    service     TEXT,                 -- which program produced it, e.g. tea-shop
    start_ns    INTEGER,              -- start time, nanoseconds since 1970 (Unix epoch)
    end_ns      INTEGER,              -- end time, same unit; duration = end - start
    status      TEXT,                 -- UNSET, OK or ERROR
    attributes  TEXT          -- JSON  -- extra key/value details, stored as JSON text
);
-- An index makes "give me all spans of trace X" fast instead of scanning every row.
CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id);
"""


class SQLiteSpanExporter(SpanExporter):
    """Receives finished spans from the SDK and writes them to SQLite."""

    def __init__(self, db_path: str = DEFAULT_DB):
        self.db_path = db_path  # remember which file to write to
        # "with" commits the changes automatically when the block ends.
        with self._connect() as db:
            db.executescript(SCHEMA)  # create the table and index if they don't exist yet

    def _connect(self):
        # timeout=10: if another program is writing, wait up to 10 s instead of failing at once.
        db = sqlite3.connect(self.db_path, timeout=10)
        # WAL (write-ahead log) mode lets readers and a writer work at the same
        # time, so several programs can safely write to the same file.
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """OpenTelemetry calls this with a batch of finished spans. This is the plug-in point."""
        rows = []  # one tuple per span, in the same column order as the table
        for s in spans:
            ctx = s.get_span_context()  # holds this span's trace_id and span_id (as integers)
            rows.append((
                format(ctx.trace_id, "032x"),  # integer -> 32-char hex string, zero-padded
                format(ctx.span_id, "016x"),  # integer -> 16-char hex string, zero-padded
                # Root spans have no parent (None -> NULL in SQL); others store the parent's id.
                format(s.parent.span_id, "016x") if s.parent else None,
                s.name,  # e.g. "boil_water"
                s.kind.name,  # enum -> text, e.g. "INTERNAL"
                # The service name was attached to the Resource in setup_tracing() below.
                s.resource.attributes.get("service.name", "unknown"),
                s.start_time,  # already in nanoseconds
                s.end_time,  # already in nanoseconds
                s.status.status_code.name,  # "UNSET", "OK" or "ERROR"
                # Attributes may be None or hold odd types; default=str turns anything
                # JSON can't handle into a string instead of crashing.
                json.dumps(dict(s.attributes or {}), default=str),
            ))
        try:
            with self._connect() as db:
                # Insert all rows in one go. The 10 "?" match the 10 columns.
                # OR REPLACE: if the same span_id is exported twice, overwrite instead of erroring.
                db.executemany(
                    "INSERT OR REPLACE INTO spans VALUES (?,?,?,?,?,?,?,?,?,?)", rows
                )
            return SpanExportResult.SUCCESS  # tell OpenTelemetry the batch was saved
        except sqlite3.Error:
            return SpanExportResult.FAILURE  # tell it we failed (the program keeps running)

    def shutdown(self) -> None:
        pass  # nothing to clean up: we open and close a connection on every export


def setup_tracing(service_name: str, db_path: str = DEFAULT_DB) -> TracerProvider:
    """One call to send this program's spans into the SQLite tracker."""
    # The provider is the factory/manager of tracing. The Resource labels every
    # span with the name of the program that made it.
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    # Connect: finished span -> SimpleSpanProcessor -> our exporter -> SQLite.
    # (Simple = export right away, no batching; fine for a demo, slower for big apps.)
    provider.add_span_processor(SimpleSpanProcessor(SQLiteSpanExporter(db_path)))
    # Make this provider the global one, so trace.get_tracer() anywhere in the
    # program uses it.
    trace.set_tracer_provider(provider)
    return provider
