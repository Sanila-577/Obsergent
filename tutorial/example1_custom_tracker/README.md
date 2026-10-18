# Example 1: a custom tracker with OpenTelemetry

Write your own OpenTelemetry exporter that saves spans to SQLite. This is
AgentTrace's storage idea in about 80 lines.

## Files

| File | Purpose |
|---|---|
| `tracker.py` | Custom exporter: finished spans -> SQLite (`traces.db`) |
| `app.py` | A small traced program (making tea) |
| `view.py` | Prints every stored trace as a tree |

## Run it

From the repository root:

```bash
uv venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt

cd tutorial/example1_custom_tracker
python app.py
python view.py
```

Expected output of `view.py` (timings vary):

```
Trace 0efd468c6480...  (4 spans)
  - make_tea  (tea-shop, 360.5 ms)
    - boil_water  (tea-shop, 200.3 ms)
    - steep_tea  (tea-shop, 100.3 ms)
    - add_sugar  (tea-shop, 50.3 ms)
```

Spans are written to `traces.db` in the folder you run from. Delete it to
start fresh. Set `TRACKER_DB=/some/path.db` to use another file.

## Try this

- Run `app.py` several times until `add_sugar` fails, then find the `[ERROR]` in the tree.
- Add a `duration_ms` column to the table and fill it in `export()`.
- Query the slowest 5 spans across all traces:
  `sqlite3 traces.db "SELECT name, (end_ns-start_ns)/1e6 FROM spans ORDER BY 2 DESC LIMIT 5"`
