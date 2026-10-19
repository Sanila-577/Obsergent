"""The corrected formula: service tiers, 1-hour cache writes, web searches, region, audio, reasoning, long prompts, thinking.

Every number is computed by hand from the provider's published rule (see docs/costs.md) with the real, trimmed price lists in
tests/fixtures/prices (gpt-4o-mini and claude-sonnet-4-5 come with their batch, priority and search prices from LiteLLM).
"""
import json
from pathlib import Path

import pytest

from obsergent.analysis.pricing import Price, cost_of_call, price_call
from obsergent.server import price_sync

FIXTURES = Path(__file__).parent / "fixtures" / "prices"


def rows():
    out = []
    for source in price_sync.SOURCES:
        parsed = price_sync.PARSERS[source](json.loads((FIXTURES / f"{source}.json").read_text()))
        out += [entry | {"source": source, "effective_from_ns": 100, "id": number} for number, entry in enumerate(parsed)]
    return out


ROWS = rows()


def call(provider, model, **tokens):
    return cost_of_call({"prompt": 0, "completion": 0} | tokens, provider, model, ROWS, None, ["ollama"])


def test_litellm_service_tiers_and_fees_are_kept_from_the_real_entries():
    parsed = price_sync.parse_litellm(json.loads((FIXTURES / "litellm.json").read_text()))
    litellm = {(r["provider"], r["model"]): r for r in parsed}
    sonnet = litellm[("anthropic", "claude-sonnet-4-5")]["extra"]
    assert sonnet["service_tiers"]["batch"] == {"input": 1.5, "output": 7.5, "cache_read": 0.15, "cache_write": 1.875}
    assert sonnet["cache_write_1h"] == 6.0 and sonnet["per_request"] == {"web_search": 0.01}
    assert litellm[("openai", "gpt-4o-mini")]["extra"]["service_tiers"]["priority"]["input"] == 0.25


def test_anthropic_batch_with_cache_uses_the_batch_prices():
    # 10,000 prompt tokens: 8,000 read from cache, 1,000 written, 1,000 plain; 500 output.
    # Batch prices per million: 1.5 in, 0.15 read, 1.875 write, 7.5 out.
    cost = call("anthropic", "claude-sonnet-4-5", prompt=10_000, completion=500, cache_read=8_000, cache_write=1_000,
                service_tier="batch")
    assert cost.usd == pytest.approx((1_000 * 1.5 + 8_000 * 0.15 + 1_000 * 1.875 + 500 * 7.5) / 1e6) and cost.tier == "batch"


def test_an_hour_long_cache_write_costs_twice_the_input_price():
    cost = call("anthropic", "claude-sonnet-4-5", prompt=1_000, completion=0, cache_write=1_000, cache_write_1h=1_000)
    assert cost.usd == pytest.approx(1_000 * 6.0 / 1e6)  # not the 3.75 of a 5-minute write
    five = call("anthropic", "claude-sonnet-4-5", prompt=1_000, completion=0, cache_write=1_000)
    assert five.usd == pytest.approx(1_000 * 3.75 / 1e6)


def test_web_searches_are_charged_per_search_on_top_of_tokens():
    cost = call("anthropic", "claude-sonnet-4-5", prompt=1_000, completion=100, web_searches=2)
    assert cost.usd == pytest.approx((1_000 * 3 + 100 * 15) / 1e6 + 2 * 0.01)  # $10 per 1,000 searches
    assert any("web search" in part["label"] for part in cost.breakdown)


def test_us_only_inference_costs_ten_percent_more_on_tokens_but_not_on_searches():
    base = call("anthropic", "claude-sonnet-4-5", prompt=1_000, completion=100)
    us = call("anthropic", "claude-sonnet-4-5", prompt=1_000, completion=100, inference_geo="us")
    assert us.usd == pytest.approx(base.usd * 1.1)
    searched = call("anthropic", "claude-sonnet-4-5", prompt=1_000, completion=100, inference_geo="us", web_searches=1)
    assert searched.usd == pytest.approx(base.usd * 1.1 + 0.01)


def test_openai_priority_uses_its_listed_price_and_flex_defaults_to_half():
    priority = call("openai", "gpt-4o-mini", prompt=1_000_000, service_tier="priority")
    assert priority.usd == pytest.approx(0.25)  # listed priority input price
    flex = call("openai", "gpt-4o-mini", prompt=1_000_000, service_tier="flex")
    assert flex.usd == pytest.approx(0.075) and "half price" in flex.note  # no flex price listed: the documented discount
    assert call("openai", "gpt-4o-mini", prompt=1_000_000, service_tier="default").usd == pytest.approx(0.15)
    assert call("openai", "gpt-4o-mini", prompt=1_000_000, service_tier="auto").usd == pytest.approx(0.15)


def test_gemini_thinking_tokens_are_billed_as_output():
    cost = call("openai", "gpt-4o-mini", prompt=0, completion=100, extra_output=50)
    assert cost.usd == pytest.approx(150 * 0.6 / 1e6)


def test_reasoning_tokens_use_their_own_price_when_the_list_has_one():
    price = Price("acme", "think", "models_dev", 0, 1.0, 4.0, reasoning=10.0)
    cost = price_call(price, prompt_tokens=0, completion_tokens=100, reasoning_tokens=40)
    assert cost.usd == pytest.approx((60 * 4.0 + 40 * 10.0) / 1e6)
    plain = price_call(Price("acme", "think", "models_dev", 0, 1.0, 4.0), 0, 100, reasoning_tokens=40)
    assert plain.usd == pytest.approx(100 * 4.0 / 1e6)  # no reasoning price: it is output


def test_audio_tokens_use_the_audio_prices():
    price = Price("acme", "voice", "models_dev", 0, 1.0, 4.0, extra={"input_audio": 20.0, "output_audio": 80.0})
    cost = price_call(price, prompt_tokens=1_000, completion_tokens=500, audio_in_tokens=400, audio_out_tokens=100)
    assert cost.usd == pytest.approx((600 * 1.0 + 400 * 20.0 + 400 * 4.0 + 100 * 80.0) / 1e6)


def test_any_long_prompt_threshold_applies_not_only_200k():
    price = Price("acme", "long", "litellm", 0, 1.0, 2.0, extra={"tiers": [
        {"input": 2.0, "output": 3.0, "tier": {"type": "context", "size": 128_000}},
        {"input": 4.0, "output": 6.0, "tier": {"type": "context", "size": 272_000}}]})
    assert price_call(price, 100_000, 0).usd == pytest.approx(0.1)
    assert price_call(price, 200_000, 0).usd == pytest.approx(0.4)
    assert price_call(price, 300_000, 0).usd == pytest.approx(1.2)


def test_the_breakdown_adds_up_to_the_total():
    cost = call("anthropic", "claude-sonnet-4-5", prompt=10_000, completion=500, cache_read=8_000, cache_write=1_000,
                web_searches=1)
    assert sum(part["usd"] for part in cost.breakdown) == pytest.approx(cost.usd)


def test_the_providers_own_charge_replaces_every_estimate_and_says_so():
    cost = call("openai", "gpt-4o-mini", prompt=1_000_000, billed_usd=0.123, billed_source="openrouter", upstream_usd=0.01)
    assert cost.usd == 0.123 and cost.confidence == "exact" and cost.source == "openrouter"
    assert "your own provider key" in cost.note
