"""What did the gateway do with a call? Classify an HTTP reply from an MCP gateway (or server).

A gateway such as WSO2 API Manager sits in front of MCP servers and applies policies. The reply
tells us the outcome, and the agent would otherwise only see "the call failed":

    decision      meaning                                   how it shows up
    allowed       the call went through                     a normal JSON-RPC result
    unauthorized  missing or invalid token                  HTTP 401
    forbidden     valid token, but not allowed to do this   HTTP 403 (e.g. the tool's scope is missing)
    throttled     rate limit (e.g. per-tool quota) hit      HTTP 429
    denied        an access-control policy blocked the tool HTTP 400 + JSON-RPC error "not allowed"
    error         anything else that went wrong             other 4xx/5xx, or a JSON-RPC error

The exact shapes are gateway-specific, so the rules are kept in this one small, tested function.
"""
# hashlib: one-way hash for the session fingerprint.
import hashlib

# The JSON-RPC code WSO2's MCP Access Control policy answers with.
DENIED_CODE = -32000


def classify(status: int, message: dict | None) -> str:
    """`status` = HTTP status of the reply, `message` = the JSON-RPC reply that belongs to the request (if any)."""
    # The JSON-RPC "error" object, if the reply has one.
    error = message.get("error") if isinstance(message, dict) else None
    # HTTP status codes are checked first: they are the gateway's own verdict.
    if status == 401:
        return "unauthorized"
    if status == 403:
        return "forbidden"
    if status == 429:
        return "throttled"
    if isinstance(error, dict):
        # A JSON-RPC error: is it the "capability not allowed" policy answer?
        text = str(error.get("message", "")).lower()
        if error.get("code") == DENIED_CODE and "not allowed" in text:
            return "denied"
        # Any other JSON-RPC error.
        return "error"
    if status >= 400:
        # Some other HTTP failure (400, 404, 500...).
        return "error"
    # Nothing wrong: the call was allowed through.
    return "allowed"


def session_hash(session_id: str | None) -> str | None:
    """A short fingerprint of an Mcp-Session-Id: enough to group calls, useless as a credential."""
    # No session id yet (e.g. before `initialize` answers).
    if not session_id:
        return None
    # sha256 is one-way: the original id cannot be recovered; keep 12 hex characters.
    return hashlib.sha256(session_id.encode()).hexdigest()[:12]


def outcome_attributes(status: int, message: dict | None, session_id: str | None,
                       activity_id: str | None = None) -> dict:
    """The span attributes that describe one HTTP reply.

    `activity_id` = WSO2 API Manager's correlation id, sent back in the `activityid` response header
    of every call. The gateway's own telemetry carries the same id (tag `span.activity.id`), so it is the
    exact key for matching a gateway span with the call it belongs to.
    """
    # Always record the HTTP status and the classified decision.
    attributes = {"http.response.status_code": status, "gateway.decision": classify(status, message)}
    # Add the session fingerprint if there is a session.
    fingerprint = session_hash(session_id)
    if fingerprint:
        attributes["mcp.session.hash"] = fingerprint
    # Add the gateway's correlation id if it sent one.
    if activity_id:
        attributes["gateway.activity_id"] = activity_id
    return attributes
