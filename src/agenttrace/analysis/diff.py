"""Find where two agent runs stopped behaving the same way.

A run is reduced to the ordered list of tool calls it made: (tool name, arguments).
Comparing two such lists tells us the first step where they differ.
"""
from agenttrace.models import Span


def _steps(spans: list[Span]) -> list[tuple[str, str]]:
    """The run as an ordered list of (tool name, arguments) - what the agent actually did."""
    calls = [s for s in spans if s.attributes.get("mcp.method.name") == "tools/call"]
    calls.sort(key=lambda s: s.start_ns)
    return [(s.attributes.get("gen_ai.tool.name", "?"), s.attributes.get("mcp.tool.arguments", ""))
            for s in calls]


def first_divergence(run_a: list[Span], run_b: list[Span]) -> dict:
    a, b = _steps(run_a), _steps(run_b)
    # zip stops at the shorter run; a length difference is handled below
    for i, (step_a, step_b) in enumerate(zip(a, b, strict=False)):
        if step_a != step_b:
            reason = "different tool" if step_a[0] != step_b[0] else "same tool, different arguments"
            return {"same": False, "step": i + 1, "reason": reason, "a": step_a, "b": step_b}
    if len(a) != len(b):  # identical so far, but one run kept going
        return {"same": False, "step": min(len(a), len(b)) + 1, "reason": "one run made more tool calls",
                "a": a[len(b)] if len(a) > len(b) else None, "b": b[len(a)] if len(b) > len(a) else None}
    return {"same": True, "steps": len(a)}
