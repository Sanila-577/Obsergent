"""The Models, Agents and MCPs pages: answers that join several tables (spans, prices, model facts).

Each function takes the storage and returns plain dicts for the REST API. The pure parts live in `analysis/`
(`modelnames`, `queries`, `agentgraph`, `mcps`); this module only gathers the data and calls them.
"""
# Group spans by trace.
from collections import defaultdict

from obsergent.analysis import pricing
from obsergent.analysis.agentgraph import build_graph, framework_of
from obsergent.analysis.generations import find_generations, to_generation
from obsergent.analysis.mcps import build_mcps
from obsergent.analysis.modelnames import display, group_key
from obsergent.analysis.queries import summarize_query
from obsergent.analysis.stats import percentile
from obsergent.server.costing import CostCalculator
from obsergent.storage.base import Backend

# What the "model info" panel shows when the price lists know nothing about a model.
NO_INFO: dict = {}


def pick_info(rows: list[dict], provider: str, canonical_name: str) -> dict:
    """The stored facts for a model: the entry of the same provider first, then any entry with the same name."""
    wanted = pricing.canonical_provider(provider)
    named = [row for row in rows if pricing.base_name(row["model"]) == canonical_name]
    same = [row for row in named if pricing.canonical_provider(row["provider"]) == wanted]
    return (same or named or [{"info": NO_INFO}])[0]["info"]


def model_catalog(store: Backend, calculator: CostCalculator) -> list[dict]:
    """One entry per model (the dated and the undated name are one): usage, cost, speed, price and what the model can do."""
    spans = store.list_llm_spans()
    groups: dict[tuple, dict] = {}
    for span in spans:
        generation = to_generation(span)
        cost = calculator.of(generation)
        key = group_key(generation.model, generation.provider)
        entry = groups.setdefault(key, {
            "model": key[1], "provider": generation.provider or "", "versions": set(), "calls": 0, "errors": 0,
            "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "reasoning_tokens": 0, "usd": 0.0,
            "exact_usd": 0.0, "unpriced": 0, "durations": [], "first_ns": span.start_ns, "last_ns": span.start_ns,
            "questions": set(), "costs": []})
        entry["versions"].add(generation.model)
        entry["calls"] += 1
        entry["errors"] += span.status_code == "ERROR"
        entry["prompt_tokens"] += generation.prompt_tokens or 0
        entry["completion_tokens"] += generation.completion_tokens or 0
        entry["cached_tokens"] += generation.cache_read_tokens
        entry["reasoning_tokens"] += generation.reasoning_tokens
        entry["usd"] += cost.usd or 0.0
        entry["exact_usd"] += (cost.usd or 0.0) if cost.confidence == "exact" else 0.0
        entry["unpriced"] += cost.status == "unpriced"
        entry["durations"].append(span.duration_ms)
        entry["first_ns"], entry["last_ns"] = min(entry["first_ns"], span.start_ns), max(entry["last_ns"], span.start_ns)
        entry["questions"].add(span.trace_id)
        entry["costs"].append((generation, cost))
    infos = store.model_info(list({pricing.base_name(name) for entry in groups.values() for name in entry["versions"] if name}
                                  | {entry["model"] for entry in groups.values()}))
    catalog = []
    for entry in groups.values():
        durations = sorted(entry.pop("durations"))
        generation, cost = entry.pop("costs")[-1]
        price, confidence, _ = pricing.choose_price(calculator.rows_for(generation.model or ""), generation.provider,
                                                    generation.model or "", None, calculator.overrides)
        local = cost.status == "local"
        info = pick_info(infos, entry["provider"], entry["model"])
        catalog.append(entry | {
            "versions": sorted(v for v in entry["versions"] if v), "questions": len(entry.pop("questions")),
            "avg_ms": sum(durations) / len(durations), "max_ms": durations[-1], "p95_ms": percentile(durations, 0.95),
            "error_rate": entry["errors"] / entry["calls"], "estimated_usd": entry["usd"] - entry["exact_usd"],
            "status": "local" if local else ("unpriced" if cost.status == "unpriced" else "priced"),
            "price": None if price is None else {
                "input": price.input, "output": price.output, "cache_read": price.cache_read,
                "cache_write": price.cache_write, "source": price.source, "confidence": confidence,
                "since_ns": price.effective_from_ns},
            "cost_usd": entry["usd"], "cost_status": "local" if local else cost.status,
            "total_tokens": entry["prompt_tokens"] + entry["completion_tokens"],
            "info": info, "display": info.get("name") or display(entry["model"])})
    return sorted(catalog, key=lambda entry: -entry["calls"])


def question_summaries(store: Backend, calculator: CostCalculator, limit: int = 50, **filters) -> list[dict]:
    """The question cards (newest first): each run that has model calls, with its cost."""
    summaries = []
    for trace in store.list_traces(limit=limit, with_models=True, **filters):
        spans = store.get_trace(trace["trace_id"])
        generations = find_generations(spans)
        cost = calculator.attach(generations)
        summaries.append(summarize_query(trace["trace_id"], spans, generations) | {"cost": cost})
    return summaries


def agent_catalog(store: Backend, calculator: CostCalculator) -> dict[str, dict]:
    """Every agent (a service that owns questions): its questions, models, tools, cost; plus the spans for its graph."""
    agents: dict[str, dict] = {}
    runs: dict[str, dict[str, list]] = defaultdict(dict)
    for trace in store.list_traces(limit=500, with_models=True):
        spans = store.get_trace(trace["trace_id"])
        generations = find_generations(spans)
        cost = calculator.attach(generations)
        summary = summarize_query(trace["trace_id"], spans, generations)
        name = summary["agent"] or "unknown agent"
        agent = agents.setdefault(name, {"name": name, "questions": 0, "model_calls": 0, "tool_calls": 0, "models": [],
                                         "tools": [], "usd": 0.0, "exchanges": 0, "problems": 0, "last_ns": 0,
                                         "first_ns": summary["started_ns"], "latest_question": ""})
        agent["questions"] += 1
        agent["model_calls"] += summary["model_calls"]
        agent["tool_calls"] += summary["tool_calls"]
        agent["exchanges"] += summary["exchanges"]
        agent["usd"] += cost.get("usd", 0.0) if cost.get("enabled") else 0.0
        agent["problems"] += summary["status"] == "problem"
        agent["models"] = list(dict.fromkeys(agent["models"] + summary["models"]))
        agent["tools"] = list(dict.fromkeys(agent["tools"] + summary["tools"]))
        if summary["started_ns"] >= agent["last_ns"]:
            agent["last_ns"], agent["latest_question"] = summary["started_ns"], summary["question"]
        agent["first_ns"] = min(agent["first_ns"], summary["started_ns"])
        runs[name][trace["trace_id"]] = spans
    for name, agent in agents.items():
        agent["framework"] = framework_of(list(runs[name].values()))
        agent["avg_exchanges"] = agent["exchanges"] / agent["questions"]
    return {name: agent | {"runs": runs[name]} for name, agent in agents.items()}


def agent_graph(store: Backend, calculator: CostCalculator, name: str) -> dict | None:
    """The aggregated graph of one agent, or None when no such agent exists."""
    agent = agent_catalog(store, calculator).get(name)
    if agent is None:
        return None
    costs = {}
    for spans in agent["runs"].values():
        for span in spans:
            if span.attributes.get("openinference.span.kind") == "LLM":
                costs[span.span_id] = calculator.of(to_generation(span)).usd or 0.0
    return build_graph(agent["runs"], costs) | {"agent": name}


def mcp_catalog(store: Backend) -> list[dict]:
    """The MCP servers with their tools, usage and tool-list changes."""
    snapshots = {server["server_name"]: store.list_tool_snapshots(server["server_name"]) for server in store.list_servers()}
    return build_mcps(snapshots, store.list_calls(limit=20000), store.list_sessions(500))
