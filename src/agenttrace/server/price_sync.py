"""Download model prices from public price lists and keep them in the database (the one outbound call AgentTrace makes).

There is no official price feed from OpenAI, Anthropic and the other providers, so four public lists are read:

    models_dev   https://models.dev/api.json            open-source database, provider by provider, dollars per MILLION tokens
    openrouter   https://openrouter.ai/api/v1/models      live list of the models OpenRouter serves, dollars per TOKEN
    huggingface  https://router.huggingface.co/v1/models  live list, dollars per MILLION tokens, per serving provider
    litellm      raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json   dollars per TOKEN

Each parser turns a list into rows of  provider, model, input, output, cache_read, cache_write, reasoning  (dollars per
million tokens, None = not stated). `refresh` downloads what is due (a list that did not change answers "304 Not Modified"
thanks to its ETag, so it is not downloaded again), stores only the prices that changed, and never raises: on a network error the
last prices stay. Nothing about your own data is sent: these are plain GET requests of public files.
"""
# json parses the downloaded lists.

# re reads LiteLLM's threshold keys.
import re

# threading runs the refresh in the background, so the server and the UI never wait for the internet.
import threading

# time gives the current time in nanoseconds.
import time

# httpx downloads the lists.
import httpx

# config.yaml: which lists, how often.
from agenttrace import config

# The database interface.
from agenttrace.storage.base import Backend

# Dollars per token -> dollars per million tokens.
MILLION = 1_000_000
# Seconds to wait for a list (models.dev is about 6 MB).
TIMEOUT = 60
# The names of the lists, in the order they are read.
SOURCES = ("models_dev", "openrouter", "huggingface", "litellm")


def per_million(value, scale: float = 1.0):
    """A price as dollars per million tokens, or None when the list does not give a real one (missing, text, negative)."""
    try:
        number = float(value) * scale
    except (TypeError, ValueError):
        return None
    # OpenRouter uses -1 for "price depends on the request": not a price.
    return round(number, 8) if number >= 0 else None


def row(provider: str, model: str, input=None, output=None, cache_read=None, cache_write=None, reasoning=None,
        extra=None) -> dict:
    """One price row, in the shape storage.save_prices expects."""
    return {"provider": provider, "model": model, "input": input, "output": output, "cache_read": cache_read,
            "cache_write": cache_write, "reasoning": reasoning, "extra": extra or {}}


def parse_models_dev(data: dict) -> list[dict]:
    """models.dev: {provider: {models: {id: {cost: {input, output, cache_read, cache_write, reasoning, tiers...}}}}}."""
    rows = []
    for provider, info in data.items():
        for model_id, model in (info.get("models") or {}).items():
            cost = model.get("cost") or {}
            if cost.get("input") is None and cost.get("output") is None:
                continue
            # Long-context tiers and other detail are kept as they are.
            extra = {key: cost[key] for key in ("context_over_200k", "tiers", "input_audio", "output_audio") if key in cost}
            rows.append(row(provider, model_id, per_million(cost.get("input")), per_million(cost.get("output")),
                            per_million(cost.get("cache_read")), per_million(cost.get("cache_write")),
                            per_million(cost.get("reasoning")), extra))
    return rows


def parse_openrouter(data: dict) -> list[dict]:
    """OpenRouter: {data: [{id: "openai/gpt-4o-mini", pricing: {prompt, completion, input_cache_read, ...}}]} per TOKEN."""
    rows = []
    for model in data.get("data", []):
        pricing = model.get("pricing") or {}
        values = [per_million(pricing.get(key), MILLION) for key in
                  ("prompt", "completion", "input_cache_read", "input_cache_write", "internal_reasoning")]
        if values[0] is None and values[1] is None:
            continue
        rows.append(row("openrouter", model["id"], *values))
    return rows


def parse_huggingface(data: dict) -> list[dict]:
    """Hugging Face router: {data: [{id, providers: [{provider, pricing: {input, output}, status}]}]} per MILLION tokens.

    A model can be served by several providers at different prices; the cheapest live one is stored, the others are kept
    in `extra` so the price can be shown as a range.
    """
    rows = []
    for model in data.get("data", []):
        offers = {}
        for provider in model.get("providers", []):
            pricing = provider.get("pricing") or {}
            if provider.get("status", "live") == "live" and pricing.get("input") is not None:
                offers[provider["provider"]] = {"input": pricing.get("input"), "output": pricing.get("output")}
        if not offers:
            continue
        cheapest = min(offers.values(), key=lambda offer: (offer["input"] or 0) + (offer["output"] or 0))
        rows.append(row("huggingface", model["id"], per_million(cheapest["input"]), per_million(cheapest["output"]),
                        extra={"providers": offers}))
    return rows


# LiteLLM price keys: the base name of each rate, and the suffixes it uses for service tiers and long prompts.
LITELLM_RATES = {"input": "input_cost_per_token", "output": "output_cost_per_token",
                 "cache_read": "cache_read_input_token_cost", "cache_write": "cache_creation_input_token_cost"}
LITELLM_SERVICE_TIERS = {"_batches": "batch", "_flex": "flex", "_priority": "priority"}
ABOVE = re.compile(r"^input_cost_per_token_above_(\d+)k_tokens$")


def litellm_rates(entry: dict, suffix: str = "") -> dict:
    """The input/output/cache rates of one LiteLLM entry for a suffix ('', '_batches', '_above_200k_tokens'), per million."""
    rates = {name: per_million(entry.get(key + suffix), MILLION) for name, key in LITELLM_RATES.items()}
    return {name: value for name, value in rates.items() if value is not None}


def litellm_extra(entry: dict) -> dict:
    """Everything beyond the plain input/output price: long-prompt tiers, service tiers, 1-hour cache write, search fee, audio."""
    extra: dict = {}
    # A higher price above N thousand prompt tokens becomes a "tier" in the same shape models.dev uses.
    tiers = []
    for key in entry:
        match = ABOVE.match(key)
        if match:
            size = int(match.group(1)) * 1000
            tiers.append(litellm_rates(entry, f"_above_{match.group(1)}k_tokens") | {"tier": {"type": "context", "size": size}})
    if tiers:
        extra["tiers"] = sorted(tiers, key=lambda tier: tier["tier"]["size"])
    # Batch / flex / priority prices.
    service = {name: litellm_rates(entry, suffix) for suffix, name in LITELLM_SERVICE_TIERS.items()}
    service = {name: rates for name, rates in service.items() if rates.get("input") is not None}
    if service:
        extra["service_tiers"] = service
    one_hour = per_million(entry.get("cache_creation_input_token_cost_above_1hr"), MILLION)
    if one_hour is not None:
        extra["cache_write_1h"] = one_hour
    # Fees per request (web search): LiteLLM lists one price per search-context size; the medium one is the usual.
    search = entry.get("search_context_cost_per_query")
    if isinstance(search, dict) and search:
        fee = search.get("search_context_size_medium", next(iter(search.values())))
        if number_or_none(fee) is not None:
            extra["per_request"] = {"web_search": float(fee)}
    for name, key in (("input_audio", "input_cost_per_audio_token"), ("output_audio", "output_cost_per_audio_token")):
        audio = per_million(entry.get(key), MILLION)
        if audio is not None:
            extra[name] = audio
    return extra


def number_or_none(value):
    """A float, or None when the value is not a number."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_litellm(data: dict) -> list[dict]:
    """LiteLLM cost map: {"gpt-4o-mini": {input_cost_per_token, output_cost_per_token, litellm_provider, ...}} per TOKEN."""
    rows = []
    for key, entry in data.items():
        # "sample_spec" is the file's own documentation entry, not a model.
        if key == "sample_spec" or not isinstance(entry, dict) or entry.get("input_cost_per_token") is None:
            continue
        provider = str(entry.get("litellm_provider") or entry.get("provider") or "unknown")
        # "together_ai/meta-llama/..." -> the model name without the provider prefix.
        model = key.split("/", 1)[1] if key.startswith(provider + "/") else key
        rows.append(row(provider, model, per_million(entry.get("input_cost_per_token"), MILLION),
                        per_million(entry.get("output_cost_per_token"), MILLION),
                        per_million(entry.get("cache_read_input_token_cost"), MILLION),
                        per_million(entry.get("cache_creation_input_token_cost"), MILLION),
                        per_million(entry.get("output_cost_per_reasoning_token"), MILLION), litellm_extra(entry)))
    return rows


# source name -> its parser
PARSERS = {"models_dev": parse_models_dev, "openrouter": parse_openrouter, "huggingface": parse_huggingface,
           "litellm": parse_litellm}


def refresh(storage: Backend, force: bool = False, client: httpx.Client | None = None) -> dict:
    """Download every list that is due and store the changed prices. Returns {source: "changed 12" | "unchanged" | ...}.

    `force` ignores the "checked recently" rule. `client` lets tests use a fake internet. Never raises.
    """
    own_client = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": "agenttrace-price-sync"})
    now = time.time_ns()
    synced = {row["source"]: row for row in storage.list_sync()}
    outcome = {}
    try:
        for name, url in config.pricing_sources().items():
            if name not in PARSERS:
                continue
            previous = synced.get(name, {})
            due = now - previous.get("checked_ns", 0) >= config.pricing_refresh_minutes(name) * 60 * 1e9
            if not (force or due):
                outcome[name] = "up to date"
                continue
            etag = previous.get("etag", "")
            try:
                reply = client.get(url, headers={"If-None-Match": etag} if etag else {})
                if reply.status_code == 304:
                    # The list did not change since the last download.
                    storage.save_sync(name, etag, previous.get("fetched_ns", now), now, previous.get("models", 0))
                    outcome[name] = "unchanged"
                    continue
                reply.raise_for_status()
                rows = PARSERS[name](reply.json())
                added = storage.save_prices(name, rows, now)
                storage.save_sync(name, reply.headers.get("etag", ""), now, now, len(rows))
                outcome[name] = f"{len(rows)} models, {added} new or changed prices"
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                # Keep the last prices; remember what went wrong so the UI can say so.
                storage.save_sync(name, previous.get("etag", ""), previous.get("fetched_ns", 0), now,
                                  previous.get("models", 0), f"{type(error).__name__}: {error}"[:300])
                outcome[name] = f"failed ({type(error).__name__})"
    finally:
        if own_client:
            client.close()
    return outcome


# One background refresher per process, and the time of the last on-demand request.
state = {"thread": None, "last_request": 0.0}
LOCK = threading.Lock()


def start_background_refresh(storage: Backend) -> None:
    """Check the lists in a daemon thread (stops with the server): each one when its own interval has passed."""
    if not (config.pricing_enabled() and config.pricing_auto_refresh()):
        return

    def loop() -> None:
        while True:
            refresh(storage)
            # Wake up every minute; each pass only touches the lists whose interval (pricing.refresh_minutes) has passed.
            time.sleep(60)

    with LOCK:
        if state["thread"] is None:
            state["thread"] = threading.Thread(target=loop, name="price-refresh", daemon=True)
            state["thread"].start()


def request_refresh(storage: Backend, minimum_gap_seconds: float = 3600) -> bool:
    """A call for a model without a price arrived: refresh in the background, but at most once per `minimum_gap_seconds`."""
    if not (config.pricing_enabled() and config.pricing_auto_refresh()):
        return False
    with LOCK:
        if time.time() - state["last_request"] < minimum_gap_seconds:
            return False
        state["last_request"] = time.time()
    threading.Thread(target=refresh, args=(storage,), kwargs={"force": True}, name="price-refresh-now", daemon=True).start()
    return True
