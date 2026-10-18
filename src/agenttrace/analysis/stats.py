"""Small statistics helpers shared by the overview, tools and gateway views."""


# The value below which `fraction` of the numbers fall (0.95 = 95th percentile).
def percentile(values: list[float], fraction: float) -> float | None:
    """The `fraction` quantile (0.95 = 95th percentile) of a list of numbers, or None for an empty list."""
    # No data: no answer.
    if not values:
        return None
    # Sort smallest to largest.
    ordered = sorted(values)
    # Pick the item at that position (min() keeps the index inside the list).
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


# Four summary numbers for a list of durations.
def latency_summary(durations_ms: list[float]) -> dict:
    """Average, median, 95th percentile and maximum of a list of durations."""
    # Nothing measured yet.
    if not durations_ms:
        # Empty answer with the same keys.
        return {"avg_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None}
    # average, median (p50), p95 and maximum.
    return {"avg_ms": sum(durations_ms) / len(durations_ms), "p50_ms": percentile(durations_ms, 0.5),
            "p95_ms": percentile(durations_ms, 0.95), "max_ms": max(durations_ms)}
