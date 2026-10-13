"""The one data shape every part of AgentTrace agrees on.

The proxy, SDK, ingest, storage, analysis and API all talk about a `Span`.
Nothing else is shared between them, which keeps each part replaceable.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Span:
    trace_id: str  # 32 hex chars; identical for every span of one run
    span_id: str  # 16 hex chars; unique per span
    parent_span_id: str | None  # the span that started this one (None for a root)
    name: str  # e.g. "tools/call search_books"
    kind: str  # INTERNAL / CLIENT / SERVER ...
    service: str  # resource attribute service.name: which program produced it
    start_ns: int  # Unix time in nanoseconds
    end_ns: int
    status_code: str = "UNSET"  # UNSET / OK / ERROR
    status_message: str = ""
    # Everything else (tool name, arguments, results, model messages...) lives here.
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        return (self.end_ns - self.start_ns) / 1e6
