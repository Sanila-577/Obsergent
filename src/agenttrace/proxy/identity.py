"""Who is calling? Read non-secret facts from the bearer token WITHOUT verifying or keeping it.

A gateway such as WSO2 API Manager hands an application a JWT access token. The token is a bearer
secret and is NEVER stored. But its payload (the middle part, plain base64 JSON) carries harmless
facts - who the caller is, which application, which scopes - that make traces much more useful
("which application made this call?").

A JWT looks like  header.payload.signature  (three base64 pieces separated by dots).

This is for DISPLAY only: the signature is not checked here (the gateway already did that), so the
values must never be used to make an authorization decision.
"""
# base64 decodes the JWT payload.
import base64

# json parses the decoded payload.
import json

# claim name(s) -> the span attribute we store. The first claim present wins.
CLAIMS = {
    "agenttrace.caller.sub": ("sub",),
    "agenttrace.caller.client_id": ("azp", "client_id", "clientId", "consumerKey"),
    "agenttrace.caller.issuer": ("iss",),
    "agenttrace.caller.audience": ("aud",),
}


def decode_payload(token: str) -> dict:
    """The JSON payload of a JWT, or {} if the token is opaque or malformed (never raises)."""
    # Split at the dots: a JWT has exactly 3 parts.
    parts = token.split(".")
    if len(parts) != 3:
        return {}  # opaque token: nothing readable inside
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)  # base64url without padding -> add it back
        # Decode the middle part and parse it as JSON.
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, UnicodeDecodeError):
        # Not valid base64/JSON: treat as unreadable.
        return {}
    # Only a JSON object (dict) is useful.
    return payload if isinstance(payload, dict) else {}


def caller_attributes(authorization: str | None) -> dict:
    """Span attributes describing the caller, taken from an `Authorization: Bearer <jwt>` header."""
    # No header, or not a bearer token: nothing to record.
    if not authorization or not authorization.lower().startswith("bearer "):
        return {}
    # Strip "Bearer " and read the payload.
    payload = decode_payload(authorization[7:].strip())
    attributes = {}
    for attribute, names in CLAIMS.items():
        # The first claim name that has a real value wins.
        value = next((payload[name] for name in names if payload.get(name) not in (None, "", [])), None)
        if isinstance(value, list):
            # Lists (like aud) are stored as comma-separated text.
            value = ",".join(str(item) for item in value)
        if value is not None:
            attributes[attribute] = str(value)
    scopes = payload.get("scope") or payload.get("scp")  # a space-separated string, or a list
    if scopes:
        attributes["agenttrace.caller.scopes"] = scopes if isinstance(scopes, str) else " ".join(map(str, scopes))
    application = payload.get("application")  # WSO2 API Manager puts the subscribing application here
    if isinstance(application, dict) and application.get("name"):
        attributes["agenttrace.caller.application"] = str(application["name"])
    return attributes
