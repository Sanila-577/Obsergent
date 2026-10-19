"""server/price_sync.py: parsers for the four public price lists (trimmed real files) and the refresh logic."""
import json
import time
from pathlib import Path

import httpx
import pytest

from agenttrace import config
from agenttrace.server import price_sync
from agenttrace.storage.sqlite import SQLiteStorage

FIXTURES = Path(__file__).parent / "fixtures" / "prices"


def load(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def find(rows, provider, model):
    return next(r for r in rows if r["provider"] == provider and r["model"] == model)


def test_models_dev_prices_are_dollars_per_million_tokens():
    rows = price_sync.parse_models_dev(load("models_dev"))
    mini = find(rows, "openai", "gpt-4o-mini")
    assert (mini["input"], mini["output"], mini["cache_read"]) == (0.15, 0.6, 0.075)
    sonnet = find(rows, "anthropic", "claude-sonnet-4-5")
    assert (sonnet["input"], sonnet["output"], sonnet["cache_read"], sonnet["cache_write"]) == (3, 15, 0.3, 3.75)
    assert find(rows, "groq", "llama-3.3-70b-versatile")["output"] == 0.79


def test_openrouter_per_token_prices_become_per_million_and_variable_prices_are_skipped():
    rows = price_sync.parse_openrouter(load("openrouter"))
    mini = find(rows, "openrouter", "openai/gpt-4o-mini")
    assert (mini["input"], mini["output"]) == (0.15, 0.6)
    assert not any(r["model"] == "openrouter/auto" for r in rows)  # -1 means "depends on the request"


def test_litellm_per_token_prices_and_the_sample_entry_is_ignored():
    rows = price_sync.parse_litellm(load("litellm"))
    assert not any(r["model"] == "sample_spec" for r in rows)
    mini = find(rows, "openai", "gpt-4o-mini")
    assert (mini["input"], mini["output"]) == (0.15, 0.6)
    together = next(r for r in rows if r["provider"] == "together_ai")
    assert together["model"] == "meta-llama/Llama-3.3-70B-Instruct-Turbo"  # provider prefix removed


def test_huggingface_keeps_the_cheapest_live_provider_and_the_others_in_extra():
    rows = price_sync.parse_huggingface(load("huggingface"))
    assert rows and all(r["provider"] == "huggingface" and r["input"] is not None for r in rows)
    assert all("providers" in r["extra"] for r in rows)


def test_well_known_models_are_still_found_in_every_list():
    """If a list changes its format, the parser silently finds nothing: this fails instead."""
    assert find(price_sync.parse_models_dev(load("models_dev")), "openai", "gpt-4o-mini")
    assert find(price_sync.parse_openrouter(load("openrouter")), "openrouter", "anthropic/claude-sonnet-4.5")
    assert find(price_sync.parse_litellm(load("litellm")), "anthropic", "claude-sonnet-4-5")


# ------------------------------------------------------------------------------------------------- refresh
@pytest.fixture
def store(tmp_path):
    return SQLiteStorage(tmp_path / "prices.db")


def fake_internet(calls, status=200, etag='"v1"', fail=False):
    """An httpx client whose 'internet' serves the fixtures, honours If-None-Match and records every request."""
    bodies = {url: name for name, url in config.pricing_sources().items()}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), request.headers.get("if-none-match")))
        if fail:
            raise httpx.ConnectError("no internet")
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304)
        return httpx.Response(status, json=load(bodies[str(request.url)]), headers={"etag": etag})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_refresh_downloads_every_list_and_stores_prices(store):
    calls = []
    outcome = price_sync.refresh(store, force=True, client=fake_internet(calls))
    assert len(calls) == 4 and all("models" in text for text in outcome.values())
    assert store.price_rows(["gpt-4o-mini"])
    assert {row["source"] for row in store.list_sync()} == set(price_sync.SOURCES)


def test_an_unchanged_list_is_not_downloaded_again_and_prices_are_not_duplicated(store):
    calls = []
    price_sync.refresh(store, force=True, client=fake_internet(calls))
    rows_before = len(store.all_current_prices())
    again = price_sync.refresh(store, force=True, client=fake_internet(calls))
    assert set(again.values()) == {"unchanged"}  # 304 Not Modified: the ETag matched
    assert len(store.all_current_prices()) == rows_before
    assert calls[-1][1] == '"v1"'  # the stored ETag was sent


def test_a_recent_check_is_not_repeated_unless_forced(store):
    calls = []
    price_sync.refresh(store, force=True, client=fake_internet(calls))
    count = len(calls)
    assert set(price_sync.refresh(store, client=fake_internet(calls)).values()) == {"up to date"}
    assert len(calls) == count


def test_a_changed_price_adds_a_history_row_and_keeps_the_old_one(store):
    sample = [price_sync.row("openai", "m", 1.0, 2.0)]
    store.save_prices("models_dev", sample, 100)
    assert store.save_prices("models_dev", sample, 200) == 0  # same price: nothing stored
    assert store.save_prices("models_dev", [price_sync.row("openai", "m", 1.5, 2.0)], 300) == 1
    history = store.price_rows(["m"])
    assert [(r["effective_from_ns"], r["input"]) for r in history] == [(100, 1.0), (300, 1.5)]


def test_a_network_failure_keeps_the_old_prices_and_records_the_error(store):
    price_sync.refresh(store, force=True, client=fake_internet([]))
    known = len(store.all_current_prices())
    outcome = price_sync.refresh(store, force=True, client=fake_internet([], fail=True))
    assert all("failed" in text for text in outcome.values())
    assert len(store.all_current_prices()) == known
    assert all(row["error"] for row in store.list_sync())


def test_refresh_never_raises_on_garbage(store):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="<html>not json</html>")))
    assert all("failed" in text for text in price_sync.refresh(store, force=True, client=client).values())


def test_request_refresh_is_rate_limited(store, monkeypatch):
    started = []
    fake_thread = type("FakeThread", (), {"start": lambda self: started.append(1)})
    monkeypatch.setattr(price_sync.threading, "Thread", lambda *args, **kwargs: fake_thread())
    price_sync.state["last_request"] = 0.0
    assert price_sync.request_refresh(store) is True
    assert price_sync.request_refresh(store) is False  # a second call within the hour does nothing
    assert time.time() - price_sync.state["last_request"] < 5
