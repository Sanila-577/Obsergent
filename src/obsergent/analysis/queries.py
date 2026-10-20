"""Questions: what someone asked an agent, and everything that happened until it answered.

A *question* is one agent run that contains at least one model call. It is not stored anywhere: it is rebuilt from the
spans of the run, so nothing needs migrating. Pure functions over spans and generations (no database, no network).

    spans of one run --find_generations()--> model calls --build_thread()--> the steps, in order
                                         \\--summarize_query()--> question, answer, models, tools, counts, tokens

A *step* is one message of the thread. Steps = human messages (what you typed) + AI messages (each model reply and each tool
use). "7 steps: 1 human, 6 AI" means you asked once, the model replied three times and used three tools.

Tokens: a model call's tokens are recorded exactly (llm.token_count.*). A tool result or your question has no count of its own
(it is part of the next model call's input), so its size is ESTIMATED from its length (characters / 4) and marked exact=False.
"""
# The shared data shape and the model-call records.
from obsergent.analysis.generations import SPAN_KIND, TOOL_KIND, Generation
from obsergent.analysis.modelnames import display
from obsergent.models import Span

# A question or answer shown as a card title is cut to this many characters.
CARD_CHARS = 140
# About how many characters make one token (the same rule as generations.tool_definition_tokens).
CHARS_PER_TOKEN = 4
# The peaks chart shows one point per question up to this many; beyond it questions are grouped into time slots.
MAX_POINTS = 40


def clean(text: str) -> str:
    """Text on one line with single spaces."""
    return " ".join((text or "").split())


def shorten(text: str, limit: int = CARD_CHARS) -> str:
    """The text cut to `limit` characters with an ellipsis."""
    text = clean(text)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def question_of(generations: list[Generation]) -> str:
    """The first thing the user asked: the first non-empty 'user' message of the first model call that has one."""
    for generation in generations:
        for message in generation.input_messages:
            if message.role == "user" and message.content.strip():
                return clean(message.content)
    return ""


def answer_of(generations: list[Generation]) -> str:
    """The final answer: the text of the last model reply that is not just a tool request."""
    for generation in reversed(generations):
        for message in reversed(generation.output_messages):
            if message.role == "assistant" and message.content.strip() and not message.tool_calls:
                return message.content.strip()
    return ""


def estimate_tokens(text: str) -> int:
    """About how many tokens a text takes (characters / 4, at least 1 for non-empty text)."""
    return max(1, round(len(text) / CHARS_PER_TOKEN)) if text else 0


def token_sums(generations: list[Generation]) -> dict:
    """Exact tokens of the model calls: input, output, cached, reasoning and their total (input + output)."""
    sums = {"input": sum(g.prompt_tokens or 0 for g in generations), "output": sum(g.completion_tokens or 0 for g in generations),
            "cached": sum(g.cache_read_tokens for g in generations), "reasoning": sum(g.reasoning_tokens for g in generations)}
    return sums | {"total": sums["input"] + sums["output"]}


def human_messages(generations: list[Generation]) -> int:
    """How many messages the person typed: the user messages the last model call saw (at least 1 when there is a question)."""
    for generation in reversed(generations):
        users = [m for m in generation.input_messages if m.role == "user" and m.content.strip()]
        if users:
            return len(users)
    return 0


def root_of(spans: list[Span]) -> Span | None:
    """The span that started the run: no parent inside the run (the earliest such span)."""
    ids = {span.span_id for span in spans}
    roots = [span for span in spans if not span.parent_span_id or span.parent_span_id not in ids]
    return min(roots, key=lambda span: span.start_ns) if roots else None


def agent_name(spans: list[Span], generations: list[Generation]) -> str:
    """The program that asked the model: the service of the first model-call span (else of the root span)."""
    by_id = {span.span_id: span for span in spans}
    for generation in generations:
        if generation.span_id in by_id:
            return by_id[generation.span_id].service
    root = root_of(spans)
    return root.service if root else ""


def tool_results(generations: list[Generation]) -> dict[str, str]:
    """tool_call_id -> the text the tool returned (the last model call saw every result in its prompt)."""
    results: dict[str, str] = {}
    for generation in generations:
        for message in generation.input_messages:
            if message.role == "tool" and message.tool_call_id:
                results[message.tool_call_id] = message.content
    return results


def build_thread(spans: list[Span], generations: list[Generation]) -> list[dict]:
    """The steps of one question in order: the question (human side), then for each model call its reply and the tools it
    used (AI side), each with its tokens."""
    by_id = {span.span_id: span for span in spans}
    results = tool_results(generations)
    thread: list[dict] = []
    question = question_of(generations)
    if question:
        thread.append({"kind": "question", "side": "human", "text": question,
                       "start_ns": generations[0].start_ns if generations else 0,
                       "tokens": {"input": estimate_tokens(question), "output": 0, "exact": False}})
    for index, generation in enumerate(generations):
        reply = next((m for m in reversed(generation.output_messages) if m.role == "assistant"), None)
        requested = [link.name for link in generation.tool_links]
        final = bool(reply and reply.content.strip() and not reply.tool_calls)
        thread.append({
            "kind": "answer" if final else "model", "side": "ai", "step": index + 1,
            "tokens": {"input": generation.prompt_tokens or 0, "output": generation.completion_tokens or 0,
                       "cached": generation.cache_read_tokens, "reasoning": generation.reasoning_tokens, "exact": True},
            "text": reply.content.strip() if reply else "",
            "model": display(generation.model), "raw_model": generation.model, "provider": generation.provider,
            "start_ns": generation.start_ns, "duration_ms": generation.latency_ms, "span_id": generation.span_id,
            "prompt_tokens": generation.prompt_tokens, "completion_tokens": generation.completion_tokens,
            "status": generation.status_code, "message": generation.status_message, "cost": generation.cost,
            "requests": requested})
        for link in generation.tool_links:
            tool_span = by_id.get(link.tool_span_id or "")
            mcp_span = by_id.get(link.mcp_span_id or "")
            result = results.get(link.tool_call_id, "")
            thread.append({
                "kind": "tool", "side": "ai", "name": link.name, "arguments": link.arguments, "result": result,
                "tokens": {"input": estimate_tokens(result), "output": 0, "exact": False},
                "span_id": link.tool_span_id, "mcp_span_id": link.mcp_span_id, "status": link.mcp_status or (
                    tool_span.status_code if tool_span else "UNSET"),
                "decision": link.gateway_decision, "server": mcp_span.attributes.get("mcp.server.name") if mcp_span else None,
                "start_ns": (mcp_span or tool_span).start_ns if (mcp_span or tool_span) else generation.end_ns,
                "duration_ms": (mcp_span or tool_span).duration_ms if (mcp_span or tool_span) else None})
    return thread


def summarize_query(trace_id: str, spans: list[Span], generations: list[Generation]) -> dict:
    """The card of one question: what was asked, the answer, when, how long, which models and tools, and how it ended."""
    start = min((span.start_ns for span in spans), default=0)
    end = max((span.end_ns for span in spans), default=0)
    tool_names = [link.name for generation in generations for link in generation.tool_links]
    tool_spans = [span for span in spans if span.attributes.get(SPAN_KIND) == TOOL_KIND]
    tools_used = list(dict.fromkeys(tool_names or [span.attributes.get("tool.name") or span.name for span in tool_spans]))
    problems = [g for g in generations if g.status_code == "ERROR"] or [s for s in spans if s.status_code == "ERROR"]
    first = next((g for g in generations if g.input_messages), None)
    root = root_of(spans)
    humans = human_messages(generations) or (1 if question_of(generations) else 0)
    return {
        "trace_id": trace_id, "question": question_of(generations), "answer": answer_of(generations),
        "started_ns": start, "duration_ms": (end - start) / 1e6, "agent": agent_name(spans, generations),
        "models": list(dict.fromkeys(display(g.model) for g in generations if g.model)), "tools": tools_used,
        "model_calls": len(generations), "tool_calls": len(tool_names),
        "human_messages": humans, "ai_messages": len(generations) + len(tool_names),
        "steps": humans + len(generations) + len(tool_names), "tokens": token_sums(generations),
        "status": "problem" if problems else "ok",
        "problem": problems[0].status_message if problems else "",
        "user_id": next((s.attributes.get("user.id") for s in spans if s.attributes.get("user.id")), None),
        "session": next((s.attributes.get("session.id") for s in spans if s.attributes.get("session.id")), None),
        "root_name": root.name if root else "", "has_input": first is not None} | {
        # The old name of `steps`, kept for one release so older scripts keep working.
        "exchanges": humans + len(generations) + len(tool_names)}


def timeline(queries: list[dict], hours: float, now_ns: int) -> dict:
    """The data of the steps chart: one point per question, or time slots when there are too many to draw one by one."""
    ordered = sorted(queries, key=lambda query: query["started_ns"])
    if len(ordered) <= MAX_POINTS:
        return {"mode": "questions", "points": [{
            "trace_id": q["trace_id"], "start_ns": q["started_ns"], "question": q["question"], "steps": q["steps"],
            "human_messages": q["human_messages"], "ai_messages": q["ai_messages"], "model_calls": q["model_calls"],
            "tool_calls": q["tool_calls"], "tokens": q["tokens"], "cost_usd": q.get("cost", {}).get("usd"),
            "duration_ms": q["duration_ms"], "models": q["models"], "tools": q["tools"], "status": q["status"]}
            for q in ordered]}
    start = now_ns - int(hours * 3600 * 1e9)
    width = max(1, (now_ns - start) // MAX_POINTS)
    slots: dict[int, list[dict]] = {}
    for query in ordered:
        slots.setdefault(min(MAX_POINTS - 1, max(0, (query["started_ns"] - start) // width)), []).append(query)

    def total(items: list[dict], key: str) -> int:
        return sum(q[key] for q in items)

    return {"mode": "slots", "points": [{
        "start_ns": start + index * width, "end_ns": start + (index + 1) * width, "count": len(items),
        "steps": total(items, "steps"), "human_messages": total(items, "human_messages"),
        "ai_messages": total(items, "ai_messages"), "model_calls": total(items, "model_calls"),
        "tool_calls": total(items, "tool_calls"),
        "tokens": {key: sum(q["tokens"][key] for q in items) for key in ("input", "output", "cached", "reasoning", "total")},
        "cost_usd": sum(q.get("cost", {}).get("usd") or 0 for q in items),
        "duration_ms": sum(q["duration_ms"] for q in items), "questions": [shorten(q["question"]) for q in items[:3]],
        "status": "problem" if any(q["status"] == "problem" for q in items) else "ok",
        "trace_id": items[-1]["trace_id"], "question": items[-1]["question"]} for index, items in sorted(slots.items())]}
