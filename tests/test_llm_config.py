"""examples/bookshop/llm.py: the LLM_* variables choose the model (no network: models are only constructed)."""
import sys

import pytest

from conftest import BOOKSHOP

sys.path.insert(0, str(BOOKSHOP.parent))
import llm  # noqa: E402  (the example's own module, found through the path added above)


def choose(monkeypatch, **variables):
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "LLM_TEMPERATURE", "GROQ_API_KEY",
                 "OPENROUTER_API_KEY", "HF_TOKEN", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    return llm.get_llm()


def test_ollama_is_the_default(monkeypatch):
    model = choose(monkeypatch)
    assert type(model).__name__ == "ChatOllama" and model.model == "qwen2.5:7b"


@pytest.mark.parametrize("provider, key_variable, host", [
    ("groq", "GROQ_API_KEY", "api.groq.com"), ("openrouter", "OPENROUTER_API_KEY", "openrouter.ai"),
    ("huggingface", "HF_TOKEN", "router.huggingface.co")])
def test_openai_compatible_services_use_their_address_and_key(monkeypatch, provider, key_variable, host):
    model = choose(monkeypatch, LLM_PROVIDER=provider, LLM_MODEL="some/model", **{key_variable: "secret-key"})
    assert type(model).__name__ == "ChatOpenAI" and host in str(model.openai_api_base)
    assert model.openai_api_key.get_secret_value() == "secret-key" and model.model_name == "some/model"


def test_a_custom_server_needs_only_a_base_url(monkeypatch):
    model = choose(monkeypatch, LLM_PROVIDER="openai_compatible", LLM_BASE_URL="http://localhost:8000/v1", LLM_MODEL="mine")
    assert str(model.openai_api_base) == "http://localhost:8000/v1"


def test_missing_model_or_url_is_a_clear_error(monkeypatch):
    with pytest.raises(SystemExit, match="LLM_MODEL"):
        choose(monkeypatch, LLM_PROVIDER="groq")
    with pytest.raises(SystemExit, match="LLM_BASE_URL"):
        choose(monkeypatch, LLM_PROVIDER="openai_compatible", LLM_MODEL="x")
