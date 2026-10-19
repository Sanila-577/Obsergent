"""Cost of model calls for the API: reads prices from the database, calls the pure functions of analysis/pricing.py.

Nothing is stored on the spans: every cost is calculated when it is asked for, from the recorded token counts and the price
table (so a refreshed price changes the numbers at once). By default each call is priced with the price valid when it was
made (`pricing.reprice: call_time`); `reprice=now` prices everything at today's prices.
"""
# asdict turns the Cost record into a plain dict for JSON.
# time gives the current time.
import time
from dataclasses import asdict

from obsergent import config
from obsergent.analysis import pricing
from obsergent.analysis.generations import Generation, find_generations, is_generation, to_generation
from obsergent.analysis.modelnames import group_key
from obsergent.models import Span
from obsergent.server import price_sync
from obsergent.storage.base import Backend

# The question shown as a title is cut to this many characters.
TITLE_CHARS = 90


class CostCalculator:
    """Prices model calls, remembering the price rows already loaded (one calculator per request)."""

    def __init__(self, store: Backend, reprice: str | None = None):
        self.store = store
        self.reprice = reprice or config.pricing_reprice()
        self.enabled = config.pricing_enabled()
        self.local = config.pricing_local_providers()
        self.overrides = config.pricing_overrides()
        # model name -> its price rows (loaded once).
        self.rows: dict[str, list[dict]] = {}
        # True when a call had no price: the lists are then refreshed in the background (at most hourly).
        self.saw_unpriced = False

    def rows_for(self, model: str) -> list[dict]:
        key = (model or "").lower()
        if key not in self.rows:
            self.rows[key] = self.store.price_rows(pricing.candidate_names(model))
        return self.rows[key]

    def of(self, generation: Generation) -> pricing.Cost:
        """The cost of one model call."""
        billed_in, billed_out = generation.billed_prompt_tokens, generation.billed_completion_tokens
        tokens = {"prompt": billed_in if billed_in is not None else generation.prompt_tokens,
                  "completion": billed_out if billed_out is not None else generation.completion_tokens,
                  "cache_read": generation.cache_read_tokens, "cache_write": generation.cache_write_tokens,
                  "cache_write_1h": generation.cache_write_1h_tokens, "audio_in": generation.audio_in_tokens,
                  "audio_out": generation.audio_out_tokens, "reasoning": generation.reasoning_tokens,
                  "web_searches": generation.web_search_requests, "service_tier": generation.service_tier,
                  "inference_geo": generation.inference_geo, "extra_output": generation.extra_output_tokens,
                  "billed_usd": generation.billed_usd, "billed_source": generation.billed_source,
                  "upstream_usd": generation.upstream_usd}
        when = None if self.reprice == "now" else generation.start_ns
        cost = pricing.cost_of_call(tokens, generation.provider, generation.model, self.rows_for(generation.model or ""), when,
                                    self.local, self.overrides)
        if cost.status == "unpriced":
            self.saw_unpriced = True
        return cost

    def attach(self, generations: list[Generation]) -> dict:
        """Put the cost on each generation (as a dict) and return the totals."""
        if not self.enabled:
            return {"enabled": False}
        costs = []
        for generation in generations:
            cost = self.of(generation)
            costs.append(cost)
            generation.cost = cost_dict(cost)
        return {"enabled": True} | pricing.sum_costs(costs)

    def finish(self) -> None:
        """Call once the answer is built: unknown models trigger a (rate-limited) background refresh of the price lists."""
        if self.saw_unpriced:
            price_sync.request_refresh(self.store)


def cost_dict(cost: pricing.Cost) -> dict:
    """The Cost record as a JSON-friendly dict."""
    data = asdict(cost)
    data["range_usd"] = list(cost.range_usd) if cost.range_usd else None
    return data


def trace_cost(calculator: CostCalculator, spans: list[Span]) -> dict:
    """Total cost of the model calls in one run's spans (no tool linking needed)."""
    return calculator.attach([to_generation(span) for span in spans if is_generation(span)])


def first_question(generations: list[Generation]) -> str:
    """The first thing the user asked in a run (the first 'user' message), used as the run's plain-language title."""
    for generation in generations:
        for message in generation.input_messages:
            if message.role == "user" and message.content.strip():
                text = " ".join(message.content.split())
                return text if len(text) <= TITLE_CHARS else text[:TITLE_CHARS - 1] + "…"
    return ""


def spending(store: Backend, since_ns: int | None, until_ns: int, buckets: int, reprice: str | None = None,
             detail: bool = True) -> dict:
    """Everything the Spending page shows for a time window (`detail=False` skips the slow per-run parts)."""
    calculator = CostCalculator(store, reprice)
    if not calculator.enabled:
        return {"enabled": False}
    spans = store.list_llm_spans(since_ns)
    generations = [to_generation(span) for span in spans]
    costs = [calculator.of(generation) for generation in generations]
    start = since_ns if since_ns is not None else min((g.start_ns for g in generations), default=until_ns)
    width = max(1, (until_ns - start) // buckets)

    by_model: dict[tuple, dict] = {}
    series = [{"start_ns": start + index * width, "usd": 0.0, "by_model": {}} for index in range(buckets)]
    by_trace: dict[str, dict] = {}
    for span, generation, cost in zip(spans, generations, costs, strict=True):
        # One entry per model: the dated and the undated name of the same model are added together.
        key = group_key(generation.model, generation.provider)
        entry = by_model.setdefault(key, {"provider": generation.provider or "", "model": key[1], "usd": 0.0, "calls": 0,
                                         "prompt_tokens": 0, "completion_tokens": 0, "status": cost.status,
                                         "confidence": cost.confidence, "note": cost.note, "source": cost.source})
        entry["calls"] += 1
        entry["prompt_tokens"] += generation.prompt_tokens or 0
        entry["completion_tokens"] += generation.completion_tokens or 0
        entry["usd"] += cost.usd or 0.0
        trace = by_trace.setdefault(span.trace_id, {"trace_id": span.trace_id, "usd": 0.0, "calls": 0, "start_ns": span.start_ns})
        trace["usd"] += cost.usd or 0.0
        trace["calls"] += 1
        trace["start_ns"] = min(trace["start_ns"], span.start_ns)
        slot = min(buckets - 1, max(0, (generation.start_ns - start) // width))
        series[slot]["usd"] += cost.usd or 0.0
        series[slot]["by_model"][key[1]] = series[slot]["by_model"].get(key[1], 0.0) + (cost.usd or 0.0)

    # The most expensive runs, with the question that was asked, and the model cost of choosing each tool.
    top = sorted(by_trace.values(), key=lambda trace: -trace["usd"])[:10]
    by_tool: dict[str, dict] = {}
    for trace in sorted(by_trace.values(), key=lambda t: -t["start_ns"])[:200] if detail else []:
        run = find_generations(store.get_trace(trace["trace_id"]))
        if trace in top:
            trace["question"] = first_question(run)
        for generation in run:
            requested = [link.name for link in generation.tool_links]
            if not requested:
                continue
            cost = calculator.of(generation).usd or 0.0
            for name in requested:
                tool = by_tool.setdefault(name, {"tool": name, "usd": 0.0, "calls": 0})
                tool["usd"] += cost / len(requested)
                tool["calls"] += 1
    for trace in top:
        trace.setdefault("question", "")

    calculator.finish()
    return {"enabled": True, "totals": pricing.sum_costs(costs),
            "by_model": sorted(by_model.values(), key=lambda entry: -entry["usd"]),
            "by_tool": sorted(by_tool.values(), key=lambda entry: -entry["usd"]),
            "series": series, "top_runs": top, "reprice": calculator.reprice}


def price_status(store: Backend) -> dict:
    """What the 'Prices checked ... ago' badge, the price-check panel and the 'prices changed' notice show."""
    sync = store.list_sync()
    return {"enabled": config.pricing_enabled(), "auto_refresh": config.pricing_auto_refresh(),
            "refresh_minutes": {name: config.pricing_refresh_minutes(name) for name in config.pricing_sources()},
            "reprice": config.pricing_reprice(), "exact_from_provider": config.pricing_exact_from_provider(),
            "sources": sync, "last_checked_ns": max((row["checked_ns"] for row in sync), default=0),
            "disagreements": pricing.find_disagreements(store.all_current_prices()) if sync else [],
            "changes": store.price_changes(time.time_ns() - 14 * 24 * 3600 * 10**9)}
