"""Facts about the cost of a model call that only the provider's own response contains.

Two providers send the real charge with every response: OpenRouter (`usage.cost`, in credits = US dollars) and xAI
(`usage.cost_in_usd_ticks`, 10 billion ticks per dollar). The OpenInference tracer records the whole model result as the span's
`output.value` text, so the charge is already stored, just buried in JSON. This module digs it out ONCE, when the span arrives,
and writes it as ordinary span attributes (so SQL and the cost code can read it cheaply):

    llm.cost.total                 the provider's own charge in dollars        (OpenInference's name for it)
    agenttrace.cost.source         "openrouter" | "xai" | "perplexity"
    agenttrace.cost.upstream_usd   OpenRouter bring-your-own-key: what YOUR provider charged

It also copies the other facts the cost formula needs (service tier, one-hour cache writes, web searches, billed units ...) out of
the same usage dictionary. Nothing here guesses a price: it only reads numbers the provider reported. Unknown shapes are ignored.
"""
# json parses the recorded model result.
import json

# re makes the cheap "is there anything to find?" check.
import re

# The span shape.
from agenttrace import config
from agenttrace.models import Span

# One xAI tick is 1e-10 US dollars.
USD_PER_TICK = 1e-10
# Look at the (possibly large) JSON only when it contains one of these words.
MARKERS = re.compile(r'"cost"|cost_in_usd_ticks|server_tool_use|ephemeral_1h|prompt_cache_hit_tokens|billed_units|'
                     r'service_tier|inference_geo|thoughts_token_count|thoughtsTokenCount')
# Never parse more than this many characters of output.value.
MAX_CHARS = 2_000_000


def is_model_call(span: Span) -> bool:
    """A model call: an OpenInference LLM span (or one that names a model) that is not MCP traffic."""
    attributes = span.attributes
    return (not attributes.get("mcp.method.name")
            and (attributes.get("openinference.span.kind") == "LLM" or attributes.get("llm.model_name") is not None))


def number(value) -> float | None:
    """A real number, or None (booleans and text are not numbers)."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def find_usage(result: dict) -> tuple[dict, dict]:
    """The usage dictionary of a recorded model result, and the extra response facts (service tier ...) next to it."""
    llm_output = result.get("llm_output") if isinstance(result.get("llm_output"), dict) else {}
    metadata = {}
    try:
        message = result["generations"][0][0]["message"]["kwargs"]
        metadata = message.get("response_metadata") or {}
    except (KeyError, IndexError, TypeError):
        pass
    candidates = [llm_output.get("token_usage"), llm_output.get("usage"), metadata.get("token_usage"), metadata.get("usage"),
                  result.get("usage")]
    usage = next((candidate for candidate in candidates if isinstance(candidate, dict)), {})
    facts = {"service_tier": llm_output.get("service_tier") or metadata.get("service_tier") or usage.get("service_tier")}
    return usage, facts


def provider_charge(usage: dict, credits_per_usd: float) -> tuple[float, str, dict] | None:
    """(dollars, source, extras) when the usage dictionary carries the provider's own charge, recognised by SHAPE.

    The provider name in the span is not reliable (LangChain says "openai" for OpenRouter and xAI), so:
    """
    ticks = number(usage.get("cost_in_usd_ticks"))
    if ticks is not None:
        return ticks * USD_PER_TICK, "xai", {}
    cost = usage.get("cost")
    if number(cost) is not None and ("is_byok" in usage or "cost_details" in usage):
        extras = {}
        details = usage.get("cost_details") if isinstance(usage.get("cost_details"), dict) else {}
        if usage.get("is_byok") and number(details.get("upstream_inference_cost")) is not None:
            extras["agenttrace.cost.upstream_usd"] = number(details["upstream_inference_cost"]) / credits_per_usd
        return number(cost) / credits_per_usd, "openrouter", extras
    if isinstance(cost, dict) and number(cost.get("total_cost")) is not None:
        return number(cost["total_cost"]), "perplexity", {}
    return None


def other_facts(usage: dict, facts: dict, attributes: dict) -> dict:
    """The remaining numbers the cost formula needs, as span attributes (only those that are present)."""
    found = {}
    if isinstance(facts.get("service_tier"), str):
        found["llm.service_tier"] = facts["service_tier"]
    # DeepSeek reports its cache hits under its own name.
    hits = number(usage.get("prompt_cache_hit_tokens"))
    if hits:
        found["llm.token_count.prompt_details.cache_read"] = int(hits)
    # Anthropic: cache writes by lifetime, searches the server ran for the model, and the region of inference.
    creation = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    if number(creation.get("ephemeral_1h_input_tokens")):
        found["agenttrace.cache_write_1h_tokens"] = int(creation["ephemeral_1h_input_tokens"])
    written = number(usage.get("cache_creation_input_tokens"))
    if written:
        found["llm.token_count.prompt_details.cache_write"] = int(written)
    tools = usage.get("server_tool_use") if isinstance(usage.get("server_tool_use"), dict) else {}
    if number(tools.get("web_search_requests")):
        found["agenttrace.web_search_requests"] = int(tools["web_search_requests"])
    if isinstance(usage.get("inference_geo"), str):
        found["agenttrace.inference_geo"] = usage["inference_geo"]
    # Cohere bills on its own "billed units", which can differ from the token counts.
    billed = usage.get("billed_units") if isinstance(usage.get("billed_units"), dict) else {}
    for name, key in (("input", "input_tokens"), ("output", "output_tokens")):
        if number(billed.get(key)) is not None:
            found[f"agenttrace.billed_units.{name}"] = int(billed[key])
    # Gemini: thinking tokens are billed as output but are reported next to (not inside) the candidate tokens.
    thoughts = number(usage.get("thoughts_token_count") or usage.get("thoughtsTokenCount"))
    candidates = number(usage.get("candidates_token_count") or usage.get("candidatesTokenCount"))
    if thoughts and candidates is not None and attributes.get("llm.token_count.completion") == int(candidates):
        found["agenttrace.extra_output_tokens"] = int(thoughts)
    return found


def billing_attributes(span: Span, credits_per_usd: float | None = None) -> dict:
    """The attributes to add to one span (empty when there is nothing to find)."""
    if not is_model_call(span):
        return {}
    text = span.attributes.get("output.value")
    if not isinstance(text, str) or len(text) > MAX_CHARS or not MARKERS.search(text):
        return {}
    try:
        result = json.loads(text)
    except (ValueError, RecursionError):
        return {}
    if not isinstance(result, dict):
        return {}
    usage, facts = find_usage(result)
    if not usage:
        return {}
    found = other_facts(usage, facts, span.attributes)
    if config.pricing_exact_from_provider():
        charge = provider_charge(usage, credits_per_usd or config.pricing_credits_per_usd())
        if charge:
            dollars, source, extras = charge
            found |= {"llm.cost.total": dollars, "agenttrace.cost.source": source} | extras
    return found


def add_billing_attributes(spans: list[Span]) -> int:
    """Add the billing attributes to every model call among `spans` (never overwriting an attribute already there)."""
    changed = 0
    for span in spans:
        found = {key: value for key, value in billing_attributes(span).items() if key not in span.attributes}
        if found:
            span.attributes.update(found)
            changed += 1
    return changed
