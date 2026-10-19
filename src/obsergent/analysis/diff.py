"""Find where two agent runs stopped behaving the same way.

A run is reduced to the ordered list of tool calls it made: (tool name, arguments).
Comparing two such lists tells us the first step where they differ.
"""
# The shared data shape.
from obsergent.models import Span


# Reduce a run to its ordered tool calls.
def tool_steps(spans: list[Span]) -> list[tuple[str, str]]:
    """The run as an ordered list of (tool name, arguments) - what the agent actually did."""
    # Keep only tools/call spans.
    calls = [s for s in spans if s.attributes.get("mcp.method.name") == "tools/call"]
    # Oldest first.
    calls.sort(key=lambda s: s.start_ns)
    # One (tool name, arguments) pair per call.
    return [(s.attributes.get("gen_ai.tool.name", "?"), s.attributes.get("mcp.tool.arguments", ""))
            for s in calls]


# Find the first step where run A and run B differ.
def first_divergence(run_a: list[Span], run_b: list[Span]) -> dict:
    # The two step lists.
    a, b = tool_steps(run_a), tool_steps(run_b)
    # zip stops at the shorter run; a length difference is handled below
    for i, (step_a, step_b) in enumerate(zip(a, b, strict=False)):
        # First difference found.
        if step_a != step_b:
            # Explain what differs.
            reason = "different tool" if step_a[0] != step_b[0] else "same tool, different arguments"
            # Report it (steps are numbered from 1).
            return {"same": False, "step": i + 1, "reason": reason, "a": step_a, "b": step_b}
    # All shared steps equal, but one run kept going.
    if len(a) != len(b):  # identical so far, but one run kept going
        # The first extra step is the divergence.
        return {"same": False, "step": min(len(a), len(b)) + 1, "reason": "one run made more tool calls",
                "a": a[len(b)] if len(a) > len(b) else None, "b": b[len(a)] if len(b) > len(a) else None}
    # Runs made exactly the same tool calls.
    return {"same": True, "steps": len(a)}
