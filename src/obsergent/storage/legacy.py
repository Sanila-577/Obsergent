"""The names this project had before it was called Obsergent, kept in ONE place so the rest of the code never mentions them.

Two things use them, once, automatically:
  * the schema step that renames the keys and the service name inside spans recorded under the old name;
  * the first start after the rename, which copies the old database to the new default location.
"""
# sqlite3's backup API copies a database (WAL file included) safely, even while another program has it open.
import sqlite3

# Path represents file locations.
from pathlib import Path

# The text that started every span attribute key (and the proxy's service name) in the old data. The quote is part of the
# pattern so only JSON KEYS are rewritten, never a value that happens to contain the word.
KEY_PREFIX = '"agenttrace.'
SERVICE = "agenttrace-proxy"
# Where the old version kept its database, and where the new one keeps it by default.
DB = Path.home() / ".agenttrace" / "agenttrace.db"
NEW_DEFAULT_DB = Path.home() / ".obsergent" / "obsergent.db"


def copy_old_database(target: Path) -> bool:
    """On the very first start under the new name: copy the old database to `target` (the old file stays as a backup).

    Only done for the default location, and only when the new file does not exist yet. Returns True when it copied.
    """
    if target != NEW_DEFAULT_DB or target.exists() or not DB.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    source, destination = sqlite3.connect(DB), sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return True
