"""What a model call costs. Pure functions: no database, no network (the prices are passed in).

    price rows (from storage.price_rows)  +  the tokens of a call  ->  a Cost

Prices are dollars per MILLION tokens. The cost of a call is `tokens x price` for each kind of token:

    uncached input   x input price
    cache reads      x cache_read price     (a repeated prompt prefix that the provider kept: much cheaper)
    cache writes     x cache_write price
    output           x output price         (reasoning tokens are part of the output and billed at the output price)

`prompt_tokens` is the number the instrumentation records for the whole prompt, which INCLUDES cached tokens (this is how
OpenAI reports it, how LangChain normalises every provider, and how OpenInference defines it), so the uncached part is
`prompt - cache_read - cache_write`. Anthropic's raw API reports the uncached part alone: `prompt_includes_cache=False`.

Which price is used when several lists know the model: see `choose_price`. The answer is always an ESTIMATE (batch discounts,
taxes, free tiers and regional prices are not modelled).
"""
# dataclass writes the constructor of the small records below.
# re finds date suffixes such as -2024-07-18 in model names.
import re
from dataclasses import dataclass, field

# Prices are per million tokens.
MILLION = 1_000_000
# Two sources "agree" when their input and output prices differ by less than this fraction.
AGREE = 0.02
# Where a model's name may carry a router or provider prefix that the price lists do not use.
ROUTING_PREFIXES = ("openrouter/", "huggingface/", "groq/", "together_ai/", "togetherai/", "fireworks_ai/", "azure/",
                    "bedrock/", "vertex_ai/", "gemini/", "ollama/")
# Names the instrumentations use -> the provider names of the price lists.
PROVIDER_ALIASES = {
    "together": "togetherai", "together_ai": "togetherai", "fireworks": "fireworks-ai", "fireworks_ai": "fireworks-ai",
    "bedrock": "amazon-bedrock", "google_genai": "google", "gemini": "google", "google-genai": "google",
    "azure_openai": "azure", "azure-openai": "azure", "vertex_ai": "google-vertex", "mistralai": "mistral",
    "hf": "huggingface", "x-ai": "xai",
}
# The sources, most trusted first, for a model that was NOT called through a router (routers: see choose_price).
SOURCE_ORDER = ("models_dev", "litellm")
# Routers bill their own price: when the call went through one, that router's live list wins.
ROUTERS = ("openrouter", "huggingface")


@dataclass
class Price:
    """One price of one model from one source (dollars per million tokens; None = not stated)."""
    provider: str
    model: str
    source: str
    effective_from_ns: int = 0
    input: float | None = None
    output: float | None = None
    cache_read: float | None = None
    cache_write: float | None = None
    reasoning: float | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class Cost:
    """The cost of one call, or why there is none."""
    usd: float | None            # None = unknown (no price found)
    status: str                  # "priced" | "local" (runs on your machine, $0) | "unpriced" (no price found)
    confidence: str = ""         # "confirmed" (two or more lists agree) | "one_source" | "disagree" | "exact" | "set_by_you"
    source: str = ""             # which list the price came from
    model: str = ""              # the model name the price was found under
    price_date_ns: int = 0       # when Obsergent first saw this price
    input_usd: float = 0.0
    output_usd: float = 0.0
    cache_usd: float = 0.0
    note: str = ""               # a plain-words explanation for tooltips
    range_usd: tuple | None = None  # (cheapest, dearest) when the lists disagree
    breakdown: list = field(default_factory=list)  # [{"label": "input", "usd": 0.0001}, ...] where the money went
    tier: str = ""               # batch / flex / priority when the call used a service tier


def canonical_provider(name: str | None) -> str:
    """'Together_AI' -> 'togetherai', 'google_genai' -> 'google': the spelling the price lists use."""
    cleaned = (name or "").strip().lower()
    return PROVIDER_ALIASES.get(cleaned, cleaned)


def normalize_model(name: str) -> str:
    """A model name without routing prefix, date suffix or ':latest', in lower case."""
    cleaned = (name or "").strip().lower()
    for prefix in ROUTING_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    cleaned = re.sub(r":latest$", "", cleaned)
    # claude-3-5-sonnet-20241022, gpt-4o-mini-2024-07-18
    cleaned = re.sub(r"-(20\d{2}-\d{2}-\d{2}|20\d{6})$", "", cleaned)
    return cleaned


def base_name(model: str) -> str:
    """The model's own name: no provider path, routing prefix or date ('openai/gpt-4o-mini-2024-07-18' -> 'gpt-4o-mini')."""
    return normalize_model(model.split("/")[-1] if "/" in model else model)


def candidate_names(model: str) -> list[str]:
    """The names to look for in the price lists, most exact first (all lower case)."""
    exact = (model or "").strip().lower()
    names = [exact, normalize_model(model)]
    # "openai/gpt-4o-mini" -> also "gpt-4o-mini"
    if "/" in exact:
        names.append(normalize_model(exact.split("/", 1)[1]))
    return list(dict.fromkeys(name for name in names if name))


def as_price(row: dict) -> Price:
    return Price(row["provider"], row["model"], row["source"], row.get("effective_from_ns", 0), row.get("input"),
                 row.get("output"), row.get("cache_read"), row.get("cache_write"), row.get("reasoning"), row.get("extra") or {})


def valid_at(rows: list[dict], when_ns: int | None) -> dict | None:
    """The newest row that was already known at `when_ns` (the newest overall when None). If the call is older than every
    row we have (a price we only learned later), the oldest row is the best answer."""
    if not rows:
        return None
    ordered = sorted(rows, key=lambda row: (row["effective_from_ns"], row.get("id", 0)))
    if when_ns is None:
        return ordered[-1]
    known = [row for row in ordered if row["effective_from_ns"] <= when_ns]
    return known[-1] if known else ordered[0]


def same_price(a: Price, b: Price) -> bool:
    """Do two lists give (almost) the same input and output price?"""
    def close(x, y):
        return (x is None and y is None) or (x is not None and y is not None and abs(x - y) <= AGREE * max(x, y, 1e-9) + 1e-9)
    return close(a.input, b.input) and close(a.output, b.output)


def fill_gaps(chosen: Price, others: list[Price]) -> Price:
    """The chosen price, with the columns it lacks taken from other lists that know the same model.

    models.dev is the main source but has no batch/flex/priority prices, 1-hour cache price or search fee; LiteLLM has them.
    Nothing the chosen list does state is ever replaced.
    """
    merged = Price(chosen.provider, chosen.model, chosen.source, chosen.effective_from_ns, chosen.input, chosen.output,
                   chosen.cache_read, chosen.cache_write, chosen.reasoning, dict(chosen.extra))
    for other in others:
        for name in ("cache_read", "cache_write", "reasoning"):
            if getattr(merged, name) is None and getattr(other, name) is not None:
                setattr(merged, name, getattr(other, name))
        for name, value in other.extra.items():
            merged.extra.setdefault(name, value)
    return merged


def choose_price(rows: list[dict], provider: str | None, model: str, when_ns: int | None = None,
                 overrides: dict | None = None) -> tuple[Price | None, str, tuple | None]:
    """Pick the price of a model from the rows of all lists. Returns (price, confidence, range_of_input+output_totals).

    Rules, in order:
      0. a price you typed in `pricing.overrides` wins;
      1. a call through a ROUTER (OpenRouter, Hugging Face) uses that router's own live list: it is what they bill;
      2. otherwise the lists' entries for the same provider (models.dev first, then LiteLLM); with no provider match, any entry
         with that model name.
    Confidence: "confirmed" when two or more lists agree, "one_source", or "disagree" (the range is returned).
    """
    names = candidate_names(model)
    for name in names:
        override = (overrides or {}).get(name) or (overrides or {}).get(model)
        if override:
            return (Price(canonical_provider(provider), name, "override", 0, override.get("input_per_million"),
                          override.get("output_per_million"), override.get("cache_read_per_million"),
                          override.get("cache_write_per_million")), "set_by_you", None)
    wanted = canonical_provider(provider)
    matching = [row for row in rows if row["model"].lower() in names]
    if not matching:
        return None, "", None
    # Newest-at-the-time row per (source, provider).
    groups: dict[tuple, list[dict]] = {}
    for row in matching:
        groups.setdefault((row["source"], canonical_provider(row["provider"]), row["model"].lower()), []).append(row)
    current = [as_price(valid_at(group, when_ns)) for group in groups.values()]
    if wanted in ROUTERS:
        pool = [price for price in current if price.source == wanted]
    else:
        same_provider = [price for price in current
                         if canonical_provider(price.provider) == wanted and price.source in SOURCE_ORDER]
        pool = same_provider or [price for price in current if price.source in SOURCE_ORDER]
    if not pool:
        return None, "", None
    # Exact model-name matches before looser ones, then the most trusted source.
    pool.sort(key=lambda price: (names.index(price.model.lower()) if price.model.lower() in names else 99,
                                 SOURCE_ORDER.index(price.source) if price.source in SOURCE_ORDER else 99))
    chosen = pool[0]
    # Other lists that know the same model from the same provider (OpenRouter ids look like "openai/gpt-4o-mini").
    chosen_provider = canonical_provider(chosen.provider)
    others = [price for price in current
              if price.source != chosen.source and base_name(price.model) == base_name(chosen.model)
              and (canonical_provider(price.provider) == chosen_provider
                   or (price.source == "openrouter" and canonical_provider(price.model.split("/")[0]) == chosen_provider))]
    chosen = fill_gaps(chosen, others)
    agreeing = [price for price in others if same_price(chosen, price)]
    differing = [price for price in others if not same_price(chosen, price)]
    if differing and not agreeing:
        totals = [(price.input or 0) + (price.output or 0) for price in [chosen, *differing]]
        return chosen, "disagree", (min(totals), max(totals))
    return chosen, "confirmed" if agreeing else "one_source", None


def clean_tier(name: str | None) -> str | None:
    """The provider's service tier as one of batch / flex / priority, or None for ordinary (standard, default, auto) pricing."""
    word = (name or "").strip().lower()
    return {"batch": "batch", "batches": "batch", "flex": "flex", "priority": "priority"}.get(word)


def rates_for(price: Price, prompt_tokens: int, tier: str | None) -> tuple[dict, list[str]]:
    """The per-million rates to use for one call, and plain-words notes about what changed them.

    Order (the providers' own rules; they stack): the service tier replaces the base rates when the price list has them
    (batch and flex default to half price when it does not: the documented discount of OpenAI, Anthropic and Google); then a
    long-prompt tier replaces them when the prompt is longer than its size.
    """
    rates = {"input": price.input, "output": price.output, "cache_read": price.cache_read, "cache_write": price.cache_write,
             "reasoning": price.reasoning, "input_audio": price.extra.get("input_audio"),
             "output_audio": price.extra.get("output_audio"), "cache_write_1h": price.extra.get("cache_write_1h")}
    notes = []
    if tier:
        listed = (price.extra.get("service_tiers") or {}).get(tier)
        if listed:
            rates.update({key: value for key, value in listed.items() if value is not None})
            notes.append(f"{tier} tier price")
        elif tier in ("batch", "flex"):
            for key in ("input", "output", "cache_read", "cache_write"):
                rates[key] = rates[key] * 0.5 if rates[key] is not None else None
            notes.append(f"{tier} tier: half price (the usual discount; no exact price listed)")
        else:
            notes.append(f"{tier} tier: its price is not listed, standard price used")
    longer = [tier_ for tier_ in (price.extra.get("tiers") or []) if (tier_.get("tier") or {}).get("size", 0) < prompt_tokens]
    if longer:
        best = max(longer, key=lambda tier_: tier_["tier"]["size"])
        rates.update({key: best[key] for key in ("input", "output", "cache_read", "cache_write") if best.get(key) is not None})
        notes.append(f"long prompt (over {best['tier']['size']:,} tokens) price")
    return rates, notes


def price_call(price: Price, prompt_tokens: int, completion_tokens: int, cache_read_tokens: int = 0,
               cache_write_tokens: int = 0, prompt_includes_cache: bool = True, *, cache_write_1h_tokens: int = 0,
               audio_in_tokens: int = 0, audio_out_tokens: int = 0, reasoning_tokens: int = 0, web_search_requests: int = 0,
               service_tier: str | None = None, inference_geo: str | None = None, extra_output_tokens: int = 0) -> Cost:
    """The cost of one call with a known price, with a breakdown of where the money went.

    uncached input x input  +  cache reads x read price  +  cache writes x write price (1-hour writes at their own price)
    +  audio in/out at their own prices  +  (output - reasoning - audio) x output  +  reasoning x reasoning price (the output
    price when none is listed)  +  searches x search fee, then x1.1 for US-only Anthropic inference.
    """
    total_prompt = prompt_tokens if prompt_includes_cache else prompt_tokens + cache_read_tokens + cache_write_tokens
    rates, notes = rates_for(price, total_prompt, clean_tier(service_tier))

    def rate(name: str, fallback: float) -> float:
        """A listed rate, or the fallback when the list does not give one."""
        return rates[name] if rates[name] is not None else fallback

    input_rate, output_rate = rate("input", 0.0), rate("output", 0.0)
    # A list that knows no cache price: cached tokens cost what normal input costs (the safe, never-too-low assumption).
    read_rate, write_rate = rate("cache_read", input_rate), rate("cache_write", input_rate)
    is_anthropic = canonical_provider(price.provider) == "anthropic" or price.model.lower().startswith("claude")
    one_hour_rate = rate("cache_write_1h", input_rate * 2 if is_anthropic else write_rate)
    uncached = prompt_tokens - cache_read_tokens - cache_write_tokens if prompt_includes_cache else prompt_tokens
    uncached = max(uncached - audio_in_tokens, 0)
    output_total = completion_tokens + extra_output_tokens
    reasoning = min(reasoning_tokens, max(output_total - audio_out_tokens, 0))
    plain_output = max(output_total - audio_out_tokens - reasoning, 0)
    five_minute_writes = max(cache_write_tokens - cache_write_1h_tokens, 0)
    # (label, group, cost in dollars x 1 million)
    parts = [
        ("input", "input", uncached * input_rate), ("cached input", "cache", cache_read_tokens * read_rate),
        ("cache writes", "cache", five_minute_writes * write_rate + cache_write_1h_tokens * one_hour_rate),
        ("audio in", "input", audio_in_tokens * rate("input_audio", input_rate)),
        ("output", "output", plain_output * output_rate), ("reasoning", "output", reasoning * rate("reasoning", output_rate)),
        ("audio out", "output", audio_out_tokens * rate("output_audio", output_rate)),
    ]
    # US-only Anthropic inference costs 1.1x on every token category.
    multiplier = 1.1 if inference_geo == "us" and is_anthropic else 1.0
    if multiplier != 1.0:
        notes.append("US-only inference: x1.1")
    breakdown = [{"label": label, "usd": amount * multiplier / MILLION} for label, _, amount in parts if amount]
    fee = (price.extra.get("per_request") or {}).get("web_search")
    if fee is None and web_search_requests and is_anthropic:
        fee = 0.01  # Anthropic: $10 per 1,000 searches
    fees = web_search_requests * (fee or 0.0)
    if web_search_requests:
        breakdown.append({"label": f"{web_search_requests} web search(es)", "usd": fees})

    def group(name: str) -> float:
        return sum(amount for _, kind, amount in parts if kind == name) * multiplier / MILLION

    return Cost(usd=sum(amount for _, _, amount in parts) * multiplier / MILLION + fees, status="priced", source=price.source,
                model=price.model, price_date_ns=price.effective_from_ns, input_usd=group("input"), output_usd=group("output"),
                cache_usd=group("cache"), note="; ".join(notes), breakdown=breakdown, tier=clean_tier(service_tier) or "")


def cost_of_call(tokens: dict, provider: str | None, model: str | None, rows: list[dict], when_ns: int | None,
                 local_providers: list[str], overrides: dict | None = None) -> Cost:
    """The whole decision for one model call.

    `tokens` = {prompt, completion, cache_read, cache_write, cache_write_1h, audio_in, audio_out, reasoning, web_searches,
    service_tier, inference_geo, extra_output, billed_usd (the provider's own charge), billed_source, upstream_usd}.
    """
    # The provider's own charge (OpenRouter, xAI) beats every estimate: it IS the bill for this call.
    if tokens.get("billed_usd") is not None:
        source = tokens.get("billed_source") or "provider"
        note = f"reported by {source} with the response"
        if tokens.get("upstream_usd"):
            note += f"; your own provider key was charged ${tokens['upstream_usd']:.6f} on top"
        return Cost(usd=float(tokens["billed_usd"]), status="priced", confidence="exact", source=source, note=note,
                    breakdown=[{"label": f"charged by {source}", "usd": float(tokens["billed_usd"])}])
    wanted = canonical_provider(provider)
    if not model or tokens.get("prompt") is None and tokens.get("completion") is None:
        return Cost(usd=None, status="unpriced", note="no token counts were recorded for this call")
    price, confidence, spread = choose_price(rows, provider, model, when_ns, overrides)
    # A model that runs on your own machine has no per-token price (unless you typed one): checked BEFORE the lists, because
    # a local model often shares its name with a hosted one (llama3.3).
    if wanted in [canonical_provider(name) for name in local_providers] and confidence != "set_by_you":
        return Cost(usd=0.0, status="local", confidence="exact", note="runs on your own machine: no per-token price")
    if price is None:
        return Cost(usd=None, status="unpriced", note=f"no price known for {model}")
    def count(name: str) -> int:
        return int(tokens.get(name) or 0)

    cost = price_call(price, count("prompt"), count("completion"), count("cache_read"), count("cache_write"),
                      cache_write_1h_tokens=count("cache_write_1h"), audio_in_tokens=count("audio_in"),
                      audio_out_tokens=count("audio_out"), reasoning_tokens=count("reasoning"),
                      web_search_requests=count("web_searches"), service_tier=tokens.get("service_tier"),
                      inference_geo=tokens.get("inference_geo"), extra_output_tokens=count("extra_output"))
    cost.confidence, cost.range_usd = confidence, spread
    return cost


def sum_costs(costs: list[Cost]) -> dict:
    """Totals for a run or a window: dollars (and the part the provider reported itself), calls priced / local / unpriced."""
    priced = [cost for cost in costs if cost.status == "priced"]
    exact = sum(cost.usd for cost in priced if cost.confidence == "exact" and cost.usd is not None)
    total = sum(cost.usd for cost in priced if cost.usd is not None)
    return {"usd": total, "exact_usd": exact, "estimated_usd": total - exact, "priced": len(priced),
            "exact": sum(cost.confidence == "exact" for cost in priced),
            "local": sum(cost.status == "local" for cost in costs), "unpriced": sum(cost.status == "unpriced" for cost in costs),
            "calls": len(costs)}


def find_disagreements(current_rows: list[dict], limit: int = 50) -> list[dict]:
    """Models whose price differs between lists (used by the 'price check' panel)."""
    by_model: dict[tuple, list[Price]] = {}
    for row in current_rows:
        if row["input"] is None or row["source"] not in ("models_dev", "litellm", "openrouter"):
            continue
        by_model.setdefault((canonical_provider(row["provider"]), normalize_model(row["model"])), []).append(as_price(row))
    found = []
    for (provider, model), prices in by_model.items():
        if len({price.source for price in prices}) > 1 and not all(same_price(prices[0], other) for other in prices[1:]):
            found.append({"provider": provider, "model": model,
                          "prices": {price.source: [price.input, price.output] for price in prices}})
    return found[:limit]
