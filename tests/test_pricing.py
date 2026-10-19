"""analysis/pricing.py: the cost formula (with the examples of the providers' own documentation), which price wins, history."""
import json
from pathlib import Path

import pytest

from agenttrace.analysis import pricing
from agenttrace.analysis.pricing import Price, cost_of_call, price_call
from agenttrace.server import price_sync

FIXTURES = Path(__file__).parent / "fixtures" / "prices"
LOCAL = ["ollama", "lmstudio"]


def rows_from_fixtures(at_ns=100):
    """Price rows as storage.price_rows returns them, built from the trimmed real price lists."""
    rows = []
    for source in price_sync.SOURCES:
        for number, entry in enumerate(price_sync.PARSERS[source](json.loads((FIXTURES / f"{source}.json").read_text()))):
            rows.append(entry | {"source": source, "effective_from_ns": at_ns, "id": number})
    return rows


ROWS = rows_from_fixtures()


def call(provider, model, prompt=1000, completion=100, when=None, **extra):
    return cost_of_call({"prompt": prompt, "completion": completion, **extra}, provider, model, ROWS, when, LOCAL)


# ------------------------------------------------------------------------------------------------- the formula
def test_anthropic_cache_example_from_the_docs():
    """Sonnet 4.5: input $3, output $15, cache read 0.1x = $0.30, 5-minute cache write 1.25x = $3.75 per million."""
    sonnet = Price("anthropic", "claude-sonnet-4-5", "models_dev", 0, 3, 15, 0.3, 3.75)
    # Prompt of 10,000 tokens: 8,000 read from the cache, 1,000 written to it, 1,000 plain; 500 tokens answered.
    cost = price_call(sonnet, prompt_tokens=10_000, completion_tokens=500, cache_read_tokens=8_000, cache_write_tokens=1_000)
    assert cost.usd == pytest.approx(0.003 + 0.0024 + 0.00375 + 0.0075)
    # Anthropic's raw API reports the 1,000 plain tokens alone: the same call gives the same cost.
    raw = price_call(sonnet, prompt_tokens=1_000, completion_tokens=500, cache_read_tokens=8_000, cache_write_tokens=1_000,
                     prompt_includes_cache=False)
    assert raw.usd == pytest.approx(cost.usd)


def test_openai_cached_tokens_are_part_of_the_prompt():
    """gpt-4o-mini: $0.15 in, $0.60 out, $0.075 cached per million. input_tokens already includes the cached ones."""
    mini = Price("openai", "gpt-4o-mini", "models_dev", 0, 0.15, 0.6, 0.075)
    cost = price_call(mini, prompt_tokens=2_000, completion_tokens=100, cache_read_tokens=1_000)
    assert cost.usd == pytest.approx(1_000 * 0.15e-6 + 1_000 * 0.075e-6 + 100 * 0.6e-6)  # 0.000285


def test_without_a_cache_price_cached_tokens_cost_the_normal_input_price():
    cost = price_call(Price("x", "m", "litellm", 0, 1.0, 2.0), 1_000, 0, cache_read_tokens=400)
    assert cost.usd == pytest.approx(1_000 * 1.0e-6)


def test_a_long_prompt_uses_the_long_context_tier():
    tiered = Price("google", "m", "models_dev", 0, 1.0, 4.0, extra={"tiers": [
        {"input": 2.0, "output": 6.0, "tier": {"type": "context", "size": 200_000}}]})
    assert price_call(tiered, 100_000, 1_000).usd == pytest.approx(0.1 + 0.004)
    assert price_call(tiered, 250_000, 1_000).usd == pytest.approx(0.5 + 0.006)


# ------------------------------------------------------------------------------------------ which price wins
def test_a_known_model_is_priced_and_confirmed_by_several_lists():
    cost = call("openai", "gpt-4o-mini")
    assert cost.status == "priced" and cost.confidence == "confirmed"
    assert cost.usd == pytest.approx(1000 * 0.15e-6 + 100 * 0.6e-6) and cost.source == "models_dev"


def test_names_with_dates_and_prefixes_still_match():
    assert call("openai", "gpt-4o-mini-2024-07-18").status == "priced"
    assert call("openai", "OpenAI/GPT-4o-mini").status == "priced"
    assert call("anthropic", "claude-sonnet-4-5-20250929").status == "priced"


def test_a_call_through_openrouter_uses_openrouters_own_price():
    cost = call("openrouter", "openai/gpt-4o-mini")
    assert cost.source == "openrouter" and cost.status == "priced"


def test_provider_specific_price_is_used_when_the_provider_is_known():
    assert call("groq", "llama-3.3-70b-versatile").usd == pytest.approx(1000 * 0.59e-6 + 100 * 0.79e-6)


def test_local_models_are_free_even_when_a_hosted_model_has_the_same_name():
    cost = call("ollama", "gpt-4o-mini")
    assert cost.status == "local" and cost.usd == 0
    assert call("ollama", "qwen2.5:7b").status == "local"


def test_an_unknown_model_is_unpriced_never_zero():
    cost = call("someprovider", "brand-new-model-1")
    assert cost.status == "unpriced" and cost.usd is None


def test_a_provider_reported_cost_beats_any_estimate():
    cost = call("openrouter", "openai/gpt-4o-mini", billed_usd=0.0123)
    assert cost.usd == 0.0123 and cost.confidence == "exact"


def test_a_price_you_typed_wins():
    overrides = {"gpt-4o-mini": {"input_per_million": 1.0, "output_per_million": 2.0}}
    cost = cost_of_call({"prompt": 1000, "completion": 1000}, "openai", "gpt-4o-mini", ROWS, None, LOCAL, overrides)
    assert cost.usd == pytest.approx(0.003) and cost.confidence == "set_by_you"


def test_lists_that_disagree_are_flagged_with_a_range():
    base = {"provider": "acme", "model": "m", "effective_from_ns": 1}
    rows = [base | {"source": "models_dev", "id": 1, "input": 1.0, "output": 2.0},
            base | {"source": "litellm", "id": 2, "input": 3.0, "output": 6.0}]
    cost = cost_of_call({"prompt": 1000, "completion": 0}, "acme", "m", rows, None, LOCAL)
    assert cost.confidence == "disagree" and cost.source == "models_dev" and cost.range_usd == (3.0, 9.0)
    assert [d["model"] for d in pricing.find_disagreements(rows)] == ["m"]


# ----------------------------------------------------------------------------------------------- price history
def history_rows():
    base = {"provider": "acme", "model": "m", "source": "models_dev", "output": 0.0}
    return [base | {"id": 1, "effective_from_ns": 100, "input": 1.0}, base | {"id": 2, "effective_from_ns": 300, "input": 2.0}]


def test_each_call_uses_the_price_valid_when_it_was_made():
    rows = history_rows()
    old = cost_of_call({"prompt": 1_000_000, "completion": 0}, "acme", "m", rows, 200, LOCAL)
    new = cost_of_call({"prompt": 1_000_000, "completion": 0}, "acme", "m", rows, 400, LOCAL)
    assert (old.usd, new.usd) == (1.0, 2.0)


def test_pricing_at_now_uses_the_newest_price_and_an_old_call_before_any_row_uses_the_oldest():
    rows = history_rows()
    assert cost_of_call({"prompt": 1_000_000, "completion": 0}, "acme", "m", rows, None, LOCAL).usd == 2.0
    assert cost_of_call({"prompt": 1_000_000, "completion": 0}, "acme", "m", rows, 50, LOCAL).usd == 1.0


def test_totals_count_priced_local_and_unpriced_calls():
    totals = pricing.sum_costs([call("openai", "gpt-4o-mini"), call("ollama", "x"), call("nobody", "unknown")])
    assert (totals["priced"], totals["local"], totals["unpriced"], totals["calls"]) == (1, 1, 1, 3)
