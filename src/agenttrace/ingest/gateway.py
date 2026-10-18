"""Make WSO2 API Manager's own telemetry easy to query.

API Manager can export OpenTelemetry traces (`[apim.open_telemetry]` in deployment.toml). Each call
through the gateway produces spans like these (verified against a real APIM 4.7 gateway):

    BookshopMCP--1.0.0--carbon.super      the whole call at the gateway   (tags span.api.name, span.activity.id,
      POST--/mcp                                                           span.http.response.status.code, ...)
        API:Key_Validation_Latency        one span per phase of the call: how long APIM spent on it
        API:Throttle_Latency
        API:Backend_Latency               ... time spent waiting for the MCP server itself

Those names are APIM-specific. This module rewrites them, at ingest time, into AgentTrace's own
attributes so the API and the UI never need to know APIM's vocabulary:

    agenttrace.layer   = "gateway"
    gateway.phase / gateway.latency_ms          on the per-phase spans
    gateway.activity_id / api / api_version / status / decision / consumer_key / path    on the call span

`gateway.activity_id` is the same id APIM returns in the `activityid` response header, which the HTTP
proxy records on its own span, so a gateway call can always be matched to the proxy call that made it.
When the proxy sends a `traceparent` header (it does), APIM continues that trace and both sides even
share one trace id.
"""
# Span is the shared data shape; classify() turns an HTTP status into allowed/denied/...
from agenttrace.models import Span
from agenttrace.proxy.gateway import classify

# --- WSO2 API Platform gateway (Envoy router + policy engine, run with docker compose) ---
# Its spans (verified against gateway 1.2.1) form this tree under the caller's traceparent:
#   router "ingress"      the whole call at the gateway (http.status_code, http.route, guid:x-request-id)
#     router "async ...ExternalProcessor.Process egress"
#       policy-engine "external_processing.process"          time inside the policy engine
#     router "router upstream_<host>_<port> egress"          time waiting for the MCP server (backend)
PLATFORM_SERVICES = ("router", "policy-engine")
# span name (or prefix) -> the phase it measures
PLATFORM_PHASES = (("external_processing.process", "policy_engine"), ("router upstream_", "backend"))

GATEWAY_SERVICE = "API:Gateway"  # service.name APIM puts on its spans
# Phase spans are named API:<Phase>_Latency, e.g. API:Backend_Latency.
PHASE_PREFIX, PHASE_SUFFIX = "API:", "_Latency"


def is_platform_span(span: Span) -> bool:
    """A span from the API Platform gateway's router or policy engine."""
    return span.service in PLATFORM_SERVICES


def platform_phase(span: Span) -> str | None:
    """'router upstream_... egress' -> 'backend'; 'external_processing.process' -> 'policy_engine'; else None."""
    for prefix, phase in PLATFORM_PHASES:
        # Exact match for the policy engine's top span (its children share the prefix), prefix match for the router's.
        if span.name == prefix or (prefix.endswith("_") and span.name.startswith(prefix)):
            return phase
    return None


def is_gateway_span(span: Span) -> bool:
    # Signs that a span came from the gateway: the API Platform's services, or APIM's service name / tag / phase name.
    return (is_platform_span(span) or span.service == GATEWAY_SERVICE or "span.activity.id" in span.attributes
            or (span.name.startswith(PHASE_PREFIX) and span.name.endswith(PHASE_SUFFIX)))


def phase_of(name: str) -> str | None:
    """'API:Key_Validation_Latency' -> 'key_validation'; anything else -> None."""
    if name.startswith(PHASE_PREFIX) and name.endswith(PHASE_SUFFIX):
        # Cut off the prefix and suffix, then lower-case what remains.
        return name[len(PHASE_PREFIX):-len(PHASE_SUFFIX)].lower()
    # Not a phase span.
    return None


def normalize_gateway_spans(spans: list[Span]) -> None:
    """Add the normalized attributes in place. Spans that are not gateway spans are left untouched."""
    for span in spans:
        # Not an APIM span: leave it alone.
        if not is_gateway_span(span):
            continue
        # Shortcut to the span's attribute dict (changes are made in place).
        attributes = span.attributes
        # Mark the span as belonging to the gateway layer (the UI colors lanes by this).
        attributes["agenttrace.layer"] = "gateway"
        if is_platform_span(span):
            normalize_platform_span(span)
            continue
        # A phase span: record which phase and how long it took.
        if phase := phase_of(span.name):
            attributes["gateway.phase"] = phase
            attributes["gateway.latency_ms"] = round(span.duration_ms, 3)
        if "span.activity.id" in attributes:  # the span that covers the whole call
            # The correlation id that also comes back in the activityid response header.
            attributes["gateway.activity_id"] = attributes["span.activity.id"]
            # Copy APIM's tag names to AgentTrace's names.
            for source, target in (("span.api.name", "gateway.api"), ("span.api.version", "gateway.api_version"),
                                   ("span.consumerkey", "gateway.consumer_key"), ("span.request.path", "gateway.path")):
                if source in attributes:
                    # Only copy tags that are present.
                    attributes[target] = attributes[source]
            # The HTTP status APIM answered with.
            status = attributes.get("span.http.response.status.code")
            if status is not None and str(status).isdigit():
                attributes["gateway.status"] = int(status)
                # Same classifier as the proxy uses, so both sides agree on the words.
                attributes["gateway.decision"] = classify(int(status), None)
                if int(status) >= 400:  # APIM leaves the span status "unset" even for a refused call: fix that
                    span.status_code = "ERROR"
                    span.status_message = f"gateway: HTTP {status} ({attributes['gateway.decision']})"


def normalize_platform_span(span: Span) -> None:
    """Fill the gateway.* attributes for a span of the API Platform gateway."""
    attributes = span.attributes
    if phase := platform_phase(span):
        # A phase span: which part of the call and how long it took.
        attributes["gateway.phase"] = phase
        attributes["gateway.latency_ms"] = round(span.duration_ms, 3)
    if span.service == "router" and span.name == "ingress":
        # The span that covers the whole call. Envoy's request id identifies it.
        attributes["gateway.activity_id"] = attributes.get("guid:x-request-id") or span.span_id
        attributes["gateway.api"] = attributes.get("http.route", "")
        attributes["gateway.path"] = attributes.get("http.route", "")
        status = attributes.get("http.status_code")
        if status is not None and str(status).isdigit():
            attributes["gateway.status"] = int(status)
            attributes["gateway.decision"] = classify(int(status), None)
            if int(status) >= 400:  # the gateway leaves the span status unset even for a refused call: fix that
                span.status_code = "ERROR"
                span.status_message = f"gateway: HTTP {status} ({attributes['gateway.decision']})"
