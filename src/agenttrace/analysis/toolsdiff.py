"""What changed between two versions of an MCP server's tool list?

Used for two questions the UI asks:
  * "how did this server's tools change over time?"            (snapshot A vs snapshot B)
  * "does the gateway show different tools than the upstream?"  (server X vs server Y)
Description changes are reported word by word, so a sneaked-in sentence is easy to spot.
"""
# difflib compares sequences (here: words).
import difflib

# json: stable text form of schemas.
import json


# Describe how to turn `before` into `after`, word by word.
def word_diff(before: str, after: str) -> list[dict]:
    """Segments [{op: equal|insert|delete, text}] that turn `before` into `after`, word by word."""
    # Split both texts into words.
    old, new = before.split(), after.split()
    # The result list of equal/insert/delete pieces.
    segments = []
    # get_opcodes lists the operations; i = range in old, j = range in new.
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        # Unchanged words.
        if tag == "equal":
            # Keep them.
            segments.append({"op": "equal", "text": " ".join(old[i1:i2])})
            # Nothing else to do for equal parts.
            continue
        # Words removed from the old text.
        if i2 > i1:
            # Record the removal.
            segments.append({"op": "delete", "text": " ".join(old[i1:i2])})
        # Words added in the new text.
        if j2 > j1:
            # Record the insertion.
            segments.append({"op": "insert", "text": " ".join(new[j1:j2])})
    # The word-level diff.
    return segments


# Compare two tool lists.
def diff_tool_lists(before: list[dict], after: list[dict]) -> dict:
    """Compare two tool lists: tools added, removed, and changed (description words and/or input schema)."""
    # Tools by name (before).
    old = {tool["name"]: tool for tool in before}
    # Tools by name (after).
    new = {tool["name"]: tool for tool in after}
    # Tools present in both but different.
    changed = []
    # Tools present in both lists.
    for name in sorted(old.keys() & new.keys()):
        # Their descriptions.
        old_text, new_text = old[name].get("description", ""), new[name].get("description", "")
        # Input schema as stable text (before).
        old_schema = json.dumps(old[name].get("inputSchema", {}), sort_keys=True)
        # Input schema as stable text (after).
        new_schema = json.dumps(new[name].get("inputSchema", {}), sort_keys=True)
        # Nothing changed for this tool: skip.
        if old_text == new_text and old_schema == new_schema:
            continue
        # Record what changed (description with word diff, and/or schema).
        changed.append({"tool": name,
                        "description_changed": old_text != new_text,
                        "description": {"before": old_text, "after": new_text, "diff": word_diff(old_text, new_text)},
                        "schema_changed": old_schema != new_schema,
                        "schema": {"before": old[name].get("inputSchema", {}),
                                   "after": new[name].get("inputSchema", {})}})
    # Tools only in one list.
    added, removed = sorted(new.keys() - old.keys()), sorted(old.keys() - new.keys())
    # Summary: identical or not, plus the details.
    return {"same": not (added or removed or changed), "added": added, "removed": removed, "changed": changed}
