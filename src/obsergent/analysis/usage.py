"""Token usage: how many tokens your agents used, where they went, and whether it is getting too much.

Pure functions over plain dicts (no database, no network); `server/catalog.py` gathers the data. Tokens are the pieces of
text a model reads (input) and writes (output); providers bill by them. Cached input is part of the input; reasoning tokens
are part of the output.

    model calls (one dict each) --usage_report()--> totals, a time series per model, and where the tokens went:
        by model, by agent, by question, by tool, the hidden cost of tool descriptions, prompts close to the model's limit
    the same calls + config     --budget_status()--> how much of today's budget is used
    the question cards          --heavy_questions()--> questions that used far more than usual
"""
# The statistics helper for "the usual" question.
from statistics import median

# The kinds of tokens counted everywhere.
KINDS = ("input", "output", "cached", "reasoning")
# A prompt that fills more than this share of the model's context window is close to its limit.
CONTEXT_WARNING = 0.8
# A question using this many times the median question is "heavy" (when no fixed alert is set).
HEAVY_FACTOR = 5
# The median needs a few questions before it means anything.
HEAVY_MIN_QUESTIONS = 5


def empty_tokens() -> dict:
    """A token counter at zero."""
    return {kind: 0 for kind in KINDS} | {"total": 0}


def add_tokens(counter: dict, call: dict) -> None:
    """Add one call's tokens to a counter (total = input + output)."""
    for kind in KINDS:
        counter[kind] += call.get(kind) or 0
    counter["total"] += (call.get("input") or 0) + (call.get("output") or 0)


def usage_report(calls: list[dict], questions: list[dict], start: int, width: int, buckets: int,
                 contexts: dict[str, int] | None = None) -> dict:
    """Everything the Usage page shows.

    `calls`: one dict per model call {trace_id, span_id, start_ns, model, provider, input, output, cached, reasoning,
    tool_definition, tools (names the call asked for), usd}. `questions`: the question cards (trace_id, question, agent,
    tokens, steps, started_ns). `contexts`: model -> context window in tokens (when the price lists know it).
    """
    contexts = contexts or {}
    totals = empty_tokens()
    series = [{"start_ns": start + index * width, **empty_tokens(), "calls": 0, "by_model": {}} for index in range(buckets)]
    by_model: dict[str, dict] = {}
    by_tool: dict[str, dict] = {}
    near_limit = []
    overhead = 0
    for call in calls:
        add_tokens(totals, call)
        slot = series[min(buckets - 1, max(0, (call["start_ns"] - start) // width))]
        add_tokens(slot, call)
        slot["calls"] += 1
        size = (call.get("input") or 0) + (call.get("output") or 0)
        slot["by_model"][call["model"]] = slot["by_model"].get(call["model"], 0) + size
        model = by_model.setdefault(call["model"], {"model": call["model"], "provider": call.get("provider") or "", "calls": 0,
                                                    "usd": 0.0, **empty_tokens()})
        add_tokens(model, call)
        model["calls"] += 1
        model["usd"] += call.get("usd") or 0.0
        overhead += call.get("tool_definition") or 0
        # The tokens of a call that chose tools are shared between those tools (as the Spending page does with dollars).
        for name in call.get("tools") or []:
            tool = by_tool.setdefault(name, {"tool": name, "calls": 0, "total": 0})
            tool["calls"] += 1
            tool["total"] += ((call.get("input") or 0) + (call.get("output") or 0)) / len(call["tools"])
        limit = contexts.get(call["model"])
        if limit and (call.get("input") or 0) > CONTEXT_WARNING * limit:
            near_limit.append({"trace_id": call["trace_id"], "span_id": call.get("span_id"), "model": call["model"],
                               "input": call.get("input") or 0, "context": limit, "share": (call.get("input") or 0) / limit})
    by_agent: dict[str, dict] = {}
    for question in questions:
        agent = by_agent.setdefault(question.get("agent") or "unknown agent", {"agent": question.get("agent") or "unknown agent",
                                                                                "questions": 0, **empty_tokens()})
        agent["questions"] += 1
        for kind in (*KINDS, "total"):
            agent[kind] += question["tokens"][kind]
    heaviest = sorted(questions, key=lambda q: -q["tokens"]["total"])[:10]
    return {
        "totals": totals | {"calls": len(calls), "questions": len(questions),
                            "avg_per_question": totals["total"] / len(questions) if questions else 0,
                            "avg_per_call": totals["total"] / len(calls) if calls else 0,
                            "cache_share": totals["cached"] / totals["input"] if totals["input"] else 0},
        "series": series,
        "by_model": sorted(by_model.values(), key=lambda m: -m["total"]),
        "by_agent": sorted(by_agent.values(), key=lambda a: -a["total"]),
        "by_tool": sorted(({**t, "total": round(t["total"])} for t in by_tool.values()), key=lambda t: -t["total"]),
        "by_question": [{"trace_id": q["trace_id"], "question": q["question"], "agent": q.get("agent"), "steps": q.get("steps"),
                         "started_ns": q["started_ns"], "tokens": q["tokens"]} for q in heaviest],
        "tool_definitions": {"total": overhead, "per_call": overhead / len(calls) if calls else 0},
        "near_limit": sorted(near_limit, key=lambda n: -n["share"])[:20],
    }


def budget_status(tokens_today: int, budget: int, warn_at_percent: float) -> dict:
    """How much of today's budget is used: off (no budget), ok, warn (from `warn_at_percent`) or over."""
    if budget <= 0:
        return {"enabled": False, "used": tokens_today}
    share = tokens_today / budget
    level = "over" if share >= 1 else "warn" if share * 100 >= warn_at_percent else "ok"
    return {"enabled": True, "used": tokens_today, "budget": budget, "share": share, "level": level,
            "warn_at_percent": warn_at_percent}


def heavy_questions(questions: list[dict], alert: int = 0) -> list[dict]:
    """Questions that used far more tokens than usual: above `alert` when it is set, else above 5x the median question."""
    totals = [q["tokens"]["total"] for q in questions if q["tokens"]["total"]]
    if alert > 0:
        limit = alert
    elif len(totals) >= HEAVY_MIN_QUESTIONS:
        limit = HEAVY_FACTOR * median(totals)
    else:
        return []
    usual = median(totals) if totals else 0
    return [{"trace_id": q["trace_id"], "question": q["question"], "tokens": q["tokens"]["total"], "started_ns": q["started_ns"],
             "times_usual": q["tokens"]["total"] / usual if usual else None, "limit": limit}
            for q in questions if q["tokens"]["total"] > limit]


def change(now: int, before: int) -> float | None:
    """The change from the previous period as a fraction (+0.12 = 12 % more); None when there was nothing before."""
    return (now - before) / before if before else None
