"""ingest/billed.py: the provider's own charge (OpenRouter, xAI) and the billing facts, dug out of a recorded model result."""
import json

import pytest

from agenttrace.ingest.billed import add_billing_attributes, billing_attributes
from agenttrace.ingest.pipeline import ingest_spans
from agenttrace.models import Span
from agenttrace.storage.sqlite import SQLiteStorage


def langchain_result(usage: dict, service_tier: str | None = None) -> str:
    """A model result as the OpenInference LangChain tracer records it in output.value (ChatOpenAI shape)."""
    llm_output = {"token_usage": usage, "model_provider": "openai", "model_name": "m"}
    if service_tier:
        llm_output["service_tier"] = service_tier
    generation = {"text": "hi", "type": "ChatGeneration", "message": {"kwargs": {"response_metadata": {}}}}
    return json.dumps({"generations": [[generation]], "llm_output": llm_output, "run": None, "type": "LLMResult"})


def model_span(output: str | None, **attributes) -> Span:
    base = {"openinference.span.kind": "LLM", "llm.model_name": "m", "llm.token_count.prompt": 100,
            "llm.token_count.completion": 20}
    if output is not None:
        base["output.value"] = output
    return Span("t" * 32, "s" * 16, None, "chat", "INTERNAL", "agent", 1, 2, attributes=base | attributes)


def test_openrouter_cost_is_read_from_the_recorded_usage():
    usage = {"prompt_tokens": 194, "completion_tokens": 2, "total_tokens": 196, "cost": 0.95, "is_byok": False,
             "cost_details": {"upstream_inference_cost": 19}}
    found = billing_attributes(model_span(langchain_result(usage)))
    assert found["llm.cost.total"] == 0.95 and found["agenttrace.cost.source"] == "openrouter"
    assert "agenttrace.cost.upstream_usd" not in found  # only for bring-your-own-key


def test_openrouter_byok_also_records_what_your_provider_charged():
    usage = {"prompt_tokens": 10, "cost": 0.0, "is_byok": True, "cost_details": {"upstream_inference_cost": 0.0012}}
    found = billing_attributes(model_span(langchain_result(usage)))
    assert found["llm.cost.total"] == 0.0 and found["agenttrace.cost.upstream_usd"] == pytest.approx(0.0012)


def test_xai_ticks_become_dollars():
    found = billing_attributes(model_span(langchain_result({"prompt_tokens": 199, "cost_in_usd_ticks": 37_756_000})))
    assert found["llm.cost.total"] == pytest.approx(0.0037756) and found["agenttrace.cost.source"] == "xai"


def test_a_plain_usage_dictionary_has_no_provider_charge():
    assert billing_attributes(model_span(langchain_result({"prompt_tokens": 5, "completion_tokens": 1, "cost": "n/a"}))) == {}


def test_other_billing_facts_are_normalised():
    usage = {"input_tokens": 105, "output_tokens": 6039, "cache_read_input_tokens": 7123, "cache_creation_input_tokens": 7345,
             "cache_creation": {"ephemeral_1h_input_tokens": 300, "ephemeral_5m_input_tokens": 7045},
             "server_tool_use": {"web_search_requests": 2}, "inference_geo": "us"}
    found = billing_attributes(model_span(langchain_result(usage, "batch")))
    assert found["llm.service_tier"] == "batch" and found["agenttrace.web_search_requests"] == 2
    assert found["agenttrace.cache_write_1h_tokens"] == 300 and found["agenttrace.inference_geo"] == "us"
    assert found["llm.token_count.prompt_details.cache_write"] == 7345


def test_deepseek_cache_hits_cohere_billed_units_and_gemini_thinking():
    deepseek = billing_attributes(model_span(langchain_result({"prompt_cache_hit_tokens": 80, "prompt_cache_miss_tokens": 20})))
    assert deepseek["llm.token_count.prompt_details.cache_read"] == 80
    billed = {"billed_units": {"input_tokens": 9, "output_tokens": 4}, "cost": None}
    cohere = billing_attributes(model_span(langchain_result(billed)))
    assert cohere["agenttrace.billed_units.input"] == 9 and cohere["agenttrace.billed_units.output"] == 4
    # Gemini: the completion count the tracer recorded equals the candidates only, so the thinking tokens are extra output.
    gemini = billing_attributes(model_span(langchain_result({"candidates_token_count": 20, "thoughts_token_count": 150})))
    assert gemini["agenttrace.extra_output_tokens"] == 150
    included = billing_attributes(model_span(langchain_result({"candidates_token_count": 20, "thoughts_token_count": 150}),
                                             **{"llm.token_count.completion": 170}))
    assert "agenttrace.extra_output_tokens" not in included


def test_the_raw_response_of_the_openai_sdk_instrumentor_is_understood_too():
    raw = json.dumps({"id": "x", "usage": {"prompt_tokens": 3, "completion_tokens": 1, "cost": 0.001, "is_byok": False}})
    assert billing_attributes(model_span(raw))["llm.cost.total"] == 0.001


@pytest.mark.parametrize("output", [None, "", "not json {", "[1, 2]", '{"cost": "just a word"}', "x" * 100])
def test_nothing_found_and_nothing_breaks(output):
    assert billing_attributes(model_span(output)) == {}


def test_mcp_spans_and_existing_attributes_are_left_alone():
    mcp = model_span(langchain_result({"cost": 1.0, "is_byok": False}), **{"mcp.method.name": "tools/call"})
    assert billing_attributes(mcp) == {}
    span = model_span(langchain_result({"cost": 1.0, "is_byok": False}), **{"llm.cost.total": 7.0})
    add_billing_attributes([span])
    assert span.attributes["llm.cost.total"] == 7.0  # never overwritten


def test_ingest_stores_the_cost_so_the_api_can_read_it(tmp_path):
    store = SQLiteStorage(tmp_path / "b.db")
    ingest_spans([model_span(langchain_result({"cost": 0.25, "is_byok": False}))], store)
    saved = store.get_trace("t" * 32)[0]
    assert saved.attributes["llm.cost.total"] == 0.25
