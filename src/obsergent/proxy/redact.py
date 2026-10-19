"""Hide secrets before anything is recorded.

Everything the proxy stores (tool arguments, results, the server command) goes
through here first. Two layers:
  * by KEY    - a dict key that looks secret ("api_key", "password"...) has its value hidden
  * by VALUE  - strings that LOOK like secrets (API keys, card numbers, emails) are masked
"""
# json turns data into text.
import json

# re = regular expressions (pattern matching on text).
import re

# config.max_attr_chars() is the default length limit.
from obsergent import config

# A dict key containing any of these words has its value replaced.
SECRET_KEYS = ("password", "token", "api_key", "apikey", "secret", "authorization", "cookie")
# Text patterns that look like secrets, wherever they appear.
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),  # API-key-like strings
    re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b"),  # card-number-like
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),  # emails
]


def redact(value):
    """Return a copy of `value` (dicts/lists/strings, nested) with secrets replaced by ***."""
    if isinstance(value, dict):
        # For each key: hide the value if the key name looks secret, otherwise redact the value recursively.
        return {k: "***" if any(w in str(k).lower() for w in SECRET_KEYS) else redact(v)
                for k, v in value.items()}
    if isinstance(value, list):
        # Redact every item of a list.
        return [redact(v) for v in value]
    if isinstance(value, str):
        # Replace every secret-looking piece of the text with ***.
        for pattern in SECRET_PATTERNS:
            value = pattern.sub("***", value)
    # Numbers, booleans, None: nothing to hide.
    return value


def to_attr(obj, limit: int | None = None) -> str:
    """Redact, turn into JSON text (sorted keys) and cut at `limit` characters.

    Sorted keys matter later: replay matches recorded tool results by their
    arguments, so the same arguments must always produce the same text.
    """
    # No limit given: use the configured default.
    limit = limit or config.max_attr_chars()
    # Redact, then write as JSON (ensure_ascii=False keeps non-English letters; default=str handles odd types).
    text = json.dumps(redact(obj), ensure_ascii=False, default=str, sort_keys=True)
    # Short enough: keep. Too long: cut and mark it.
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


def safe_command(command: list[str]) -> str:
    """The server command as one string, safe to store (secret-looking arguments hidden).

    Servers are often started like `npx some-server --token abc123`, so we hide
    the value after a secret-looking flag and any argument that looks like a secret.
    """
    # out = words to keep; hide_next = "the next word is a secret value".
    out, hide_next = [], False
    for arg in command:
        if hide_next:
            # This word is the value of a secret flag: hide it.
            out.append("***")
            hide_next = False
            continue
        flag = arg.lower().replace("-", "_")  # "--api-key" must match the secret word "api_key"
        if arg.startswith("-") and any(w in flag for w in SECRET_KEYS):
            hide_next = "=" not in arg  # "--token abc" hides the next word; "--token=abc" is inside this one
            out.append(arg.split("=")[0] + "=***" if "=" in arg else arg)
            continue
        # Ordinary word: only mask secret-looking patterns inside it.
        out.append(redact(arg))
    # Join back into one string.
    return " ".join(out)
