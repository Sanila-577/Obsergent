"""view.py - print every trace in the SQLite tracker as a tree."""
import json  # to decode the attributes column back into a dictionary
import sqlite3  # to read the database
import sys  # to read the command-line argument

# Optional first argument = path to the database: python view.py other.db
# With no argument, use traces.db in the current folder.
db_path = sys.argv[1] if len(sys.argv) > 1 else "traces.db"
db = sqlite3.connect(db_path)
db.row_factory = sqlite3.Row  # rows behave like dicts: r["name"] instead of r[3]
# Load every span, oldest first, so children appear in the order they ran.
rows = db.execute("SELECT * FROM spans ORDER BY start_ns").fetchall()

# Group spans by trace_id: {trace_id: [span, span, ...]}.
# setdefault creates the empty list the first time we see a trace_id.
traces: dict[str, list] = {}
for r in rows:
    traces.setdefault(r["trace_id"], []).append(r)


def show(span, children, depth):
    """Print one span, then (recursively) all of its children, indented deeper."""
    ms = (span["end_ns"] - span["start_ns"]) / 1e6  # nanoseconds -> milliseconds
    flag = "  [ERROR]" if span["status"] == "ERROR" else ""  # highlight failed spans
    attrs = json.loads(span["attributes"])  # JSON text -> dict
    extra = ""
    # Show the first "interesting" attribute found (tool name, model name...).
    # These keys are used by later examples; the tea-shop spans have none, so extra stays empty.
    for key in ("gen_ai.tool.name", "mcp.method.name", "llm.model_name", "gen_ai.request.model"):
        if key in attrs:
            extra = f"  {key}={attrs[key]}"
            break  # only show one
    # Two spaces of indentation per tree level.
    print(f"{'  ' * depth}- {span['name']}  ({span['service']}, {ms:.1f} ms){extra}{flag}")
    # Look up this span's children by its span_id and print each one a level deeper.
    for child in children.get(span["span_id"], []):
        show(child, children, depth + 1)


# Build and print one tree per trace.
for trace_id, spans in traces.items():
    ids = {s["span_id"] for s in spans}  # set of all span ids in this trace
    # children maps parent_id -> list of its child spans.
    children: dict[str, list] = {}
    for s in spans:
        children.setdefault(s["parent_id"], []).append(s)
    # A root is a span whose parent is not in this trace (None for a true root).
    roots = [s for s in spans if s["parent_id"] not in ids]
    # Show only the first 12 characters of the long trace id.
    print(f"\nTrace {trace_id[:12]}...  ({len(spans)} spans)")
    for root in roots:
        show(root, children, 1)  # depth 1 = one level of indentation
