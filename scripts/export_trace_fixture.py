"""Export one recorded trace as a JSON fixture for tests (home folder paths are anonymised).

    OBSERGENT_DB=/path/to/obsergent.db python scripts/export_trace_fixture.py <trace id prefix> [<prefix> ...] \\
        tests/fixtures/run.json
(the last argument is the output file; several traces can go into one fixture)
"""
import json
import sys
from dataclasses import asdict
from pathlib import Path

from obsergent import config
from obsergent.storage.sqlite import SQLiteStorage

HOME = str(Path.home())


def anonymise(value):
    """Replace the user's home folder in every string, so fixtures can be committed."""
    if isinstance(value, str):
        return value.replace(HOME, "/home/user")
    if isinstance(value, dict):
        return {key: anonymise(item) for key, item in value.items()}
    if isinstance(value, list):
        return [anonymise(item) for item in value]
    return value


def main() -> int:
    if len(sys.argv) < 3:
        sys.exit("usage: python scripts/export_trace_fixture.py <trace id prefix> [<prefix> ...] <output.json>")
    prefixes, output = sys.argv[1:-1], Path(sys.argv[-1])
    store = SQLiteStorage(config.db_path())
    spans = []
    for prefix in prefixes:
        trace_id = store.resolve_trace_id(prefix)
        if not trace_id:
            sys.exit(f"no trace starting with '{prefix}' in {config.db_path()}")
        spans += [anonymise(asdict(span)) for span in store.get_trace(trace_id)]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(spans, indent=1, sort_keys=True))
    print(f"wrote {len(spans)} spans of {len(prefixes)} trace(s) to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
