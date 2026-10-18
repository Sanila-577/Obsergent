"""llm.py - which language model the agent uses. Configured in the .env file in the repository root.

    LLM_PROVIDER   ollama (default) | openai | anthropic | google | groq | openrouter | huggingface | together |
                   fireworks | deepseek | mistral | xai | perplexity | lmstudio | openai_compatible | any other
                   provider LangChain knows (bedrock, cohere, ...)
    LLM_MODEL      the model name at that provider, e.g. qwen2.5:7b, gpt-4o-mini, llama-3.3-70b-versatile
    LLM_API_KEY    optional: the key (otherwise the provider's usual variable is used, e.g. GROQ_API_KEY)
    LLM_BASE_URL   optional: another server address (any OpenAI-compatible server: vLLM, llama.cpp, LM Studio, ...)

How it adapts: most hosted and open-source model services (Groq, OpenRouter, Hugging Face, Together, Fireworks,
DeepSeek, vLLM, ...) speak the OpenAI API, so they are all reached with one client and a different address and key.
Ollama, Anthropic and Google use their own clients. See `.env.example` for a ready line for each provider.
"""
# os reads environment variables.
import os

# Path locates the .env file.
from pathlib import Path

# load_dotenv copies the lines of a .env file into the environment.
from dotenv import load_dotenv

# init_chat_model builds a chat model for a provider from a model name.
from langchain.chat_models import init_chat_model

# The repository root holds .env (this file is examples/bookshop/llm.py). Variables already set in the shell win.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

# OpenAI-compatible services: provider -> (base URL, the variable that normally holds its key).
OPENAI_COMPATIBLE = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "huggingface": ("https://router.huggingface.co/v1", "HF_TOKEN"),
    "together": ("https://api.together.xyz/v1", "TOGETHER_API_KEY"),
    "fireworks": ("https://api.fireworks.ai/inference/v1", "FIREWORKS_API_KEY"),
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
    "perplexity": ("https://api.perplexity.ai", "PERPLEXITY_API_KEY"),
    "lmstudio": ("http://localhost:1234/v1", ""),  # a local server, no key needed
    "openai_compatible": ("", "OPENAI_API_KEY"),  # your own server: set LLM_BASE_URL
}
# Providers whose LangChain name differs from the name used in .env.
LANGCHAIN_NAMES = {"google": "google_genai"}
# Used when LLM_MODEL is empty (only Ollama has a default; for the others you choose).
DEFAULT_MODELS = {"ollama": "qwen2.5:7b"}


def get_llm():
    """Return the chat model described by the LLM_* variables."""
    provider = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()
    model = os.environ.get("LLM_MODEL", "").strip() or DEFAULT_MODELS.get(provider, "")
    if not model:
        raise SystemExit(f"LLM_MODEL is not set for provider '{provider}': add it to .env (see .env.example)")
    # Settings shared by every model; temperature 0 = no randomness, so the same question gives the same answer.
    options: dict = {"temperature": float(os.environ.get("LLM_TEMPERATURE", "0"))}
    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    try:
        if provider in OPENAI_COMPATIBLE:
            default_url, key_variable = OPENAI_COMPATIBLE[provider]
            # One OpenAI-style client, pointed at that service's address with that service's key.
            options["base_url"] = base_url or default_url
            if not options["base_url"]:
                raise SystemExit(f"provider '{provider}' needs LLM_BASE_URL in .env")
            # Local servers need no key, but the client wants some text.
            options["api_key"] = api_key or os.environ.get(key_variable, "") or "not-needed"
            return init_chat_model(model, model_provider="openai", **options)
        if provider == "ollama":
            # Where the Ollama server listens (its default port is 11434).
            options["base_url"] = base_url or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        elif base_url:
            options["base_url"] = base_url
        if api_key:
            options["api_key"] = api_key
        return init_chat_model(model, model_provider=LANGCHAIN_NAMES.get(provider, provider), **options)
    except ImportError as error:
        # LangChain says which package is missing; add where to put it.
        raise SystemExit(f"provider '{provider}' needs another package: {error}") from error
