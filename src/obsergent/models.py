"""The one data shape every part of Obsergent agrees on.

The proxy, SDK, ingest, storage, analysis and API all talk about a `Span`.
Nothing else is shared between them, which keeps each part replaceable.

A *span* is one step of a run: "boil the water", "call the search_books tool", "ask the model". It has a name,
a start time, an end time, a status and a bag of extra details. Spans that belong to one run share a `trace_id`;
a span points at the span that started it with `parent_span_id`, so all spans of a run form a tree.
"""
# `dataclass` writes the boring parts of a class for us (the constructor, equality, printing); `field` customises one attribute.
from dataclasses import dataclass, field

# `Any` is a type hint meaning "any kind of value".
from typing import Any


# @dataclass turns the attribute list below into a ready-made class: Span(trace_id=..., span_id=..., ...).
@dataclass
class Span:
    # A 32-character hex string; identical for every span of one run (that is how spans find each other).
    trace_id: str
    # A 16-character hex string; unique to this span.
    span_id: str
    # The id of the span that started this one; None means "I am the root of the tree".
    parent_span_id: str | None
    # What happened, e.g. "tools/call search_books".
    name: str
    # The role of the span: INTERNAL (inside one program), CLIENT (sends a request), SERVER (handles a request)...
    kind: str
    # Which program produced it (the OpenTelemetry resource attribute service.name), e.g. "bookshop-agent".
    service: str
    # When it started, in nanoseconds since 1970 (the "Unix epoch"): a big integer that sorts correctly.
    start_ns: int
    # When it ended, in the same unit; duration = end - start.
    end_ns: int
    # Outcome: UNSET (nothing said), OK, or ERROR. A default value means callers may leave it out.
    status_code: str = "UNSET"
    # A human-readable reason when the status is ERROR.
    status_message: str = ""
    # Everything else (tool name, arguments, results, model messages...) lives in this dictionary.
    # default_factory=dict gives every Span its OWN empty dict (a plain `= {}` would be shared by all spans).
    attributes: dict[str, Any] = field(default_factory=dict)
    # Timestamped notes inside a span (OpenTelemetry "events"); a list of small dictionaries.
    events: list[dict[str, Any]] = field(default_factory=list)

    # A property is a computed attribute: reading `span.duration_ms` runs this method, no parentheses needed.
    @property
    def duration_ms(self) -> float:
        # Nanoseconds -> milliseconds: divide by one million (1e6).
        return (self.end_ns - self.start_ns) / 1e6
